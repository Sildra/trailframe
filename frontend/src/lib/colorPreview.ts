import { effectiveCorrection, type CorrectionSettings } from "./reprocess";

/** RGBA pixels, compatible with the browser's `ImageData`. */
export interface PixelData {
    width: number;
    height: number;
    data: Uint8ClampedArray;
}

const clamp = (value: number, low: number, high: number) => Math.max(low, Math.min(high, value));

function boxBlur(values: Float32Array, width: number, height: number, radius: number): Float32Array {
    const r = Math.max(1, Math.round(radius));
    const horizontal = new Float32Array(values.length);
    const output = new Float32Array(values.length);

    for (let y = 0; y < height; y += 1) {
        const row = y * width;
        let sum = 0;

        for (let x = -r; x <= r; x += 1) {
            sum += values[row + clamp(x, 0, width - 1)];
        }

        const divisor = Math.min(width, 2 * r + 1);

        for (let x = 0; x < width; x += 1) {
            horizontal[row + x] = sum / divisor;
            sum -= values[row + clamp(x - r, 0, width - 1)];
            sum += values[row + clamp(x + r + 1, 0, width - 1)];
        }
    }

    for (let x = 0; x < width; x += 1) {
        let sum = 0;

        for (let y = -r; y <= r; y += 1) {
            sum += horizontal[clamp(y, 0, height - 1) * width + x];
        }

        const divisor = Math.min(height, 2 * r + 1);

        for (let y = 0; y < height; y += 1) {
            output[y * width + x] = sum / divisor;
            sum -= horizontal[clamp(y - r, 0, height - 1) * width + x];
            sum += horizontal[clamp(y + r + 1, 0, height - 1) * width + x];
        }
    }

    return output;
}

function luminance(data: Uint8ClampedArray, index: number): number {
    return 0.299 * data[index] + 0.587 * data[index + 1] + 0.114 * data[index + 2];
}

function percentile(sorted: number[], fraction: number): number {
    if (sorted.length === 0) {
        return 0;
    }

    const position = clamp(fraction, 0, 1) * (sorted.length - 1);
    const low = Math.floor(position);
    const high = Math.ceil(position);

    return sorted[low] + (sorted[high] - sorted[low]) * (position - low);
}

function sampledLuminance(data: Uint8ClampedArray): number[] {
    const values: number[] = [];
    const count = data.length / 4;
    const stride = Math.max(1, Math.floor(count / 5000));

    for (let pixel = 0; pixel < count; pixel += stride) {
        values.push(luminance(data, pixel * 4));
    }

    return values.sort((a, b) => a - b);
}

function applyExposure(pixels: PixelData, options: CorrectionSettings): void {
    const gain = 2 ** clamp(options.exposure.exposure, -6, 6);
    const inverseGamma = 1 / clamp(options.exposure.gamma, 0.2, 5);
    const lut = new Uint8ClampedArray(256);

    for (let value = 0; value < 256; value += 1) {
        lut[value] = 255 * (value / 255) ** inverseGamma * gain;
    }

    for (let index = 0; index < pixels.data.length; index += 4) {
        pixels.data[index] = lut[pixels.data[index]];
        pixels.data[index + 1] = lut[pixels.data[index + 1]];
        pixels.data[index + 2] = lut[pixels.data[index + 2]];
    }
}

function applyWhiteBalance(pixels: PixelData, options: CorrectionSettings): void {
    const { method, strength, temperature, tint } = options.whiteBalance;
    const manual = [
        1 + 0.25 * temperature + 0.1 * tint,
        1 - 0.1 * tint,
        1 - 0.25 * temperature + 0.1 * tint,
    ];
    let detected = manual;

    if (method === "gray_world") {
        const sums = [0, 0, 0];
        let used = 0;
        const count = pixels.data.length / 4;
        const stride = Math.max(1, Math.floor(count / 5000));

        for (let pixel = 0; pixel < count; pixel += stride) {
            const index = pixel * 4;
            const luma = luminance(pixels.data, index);

            if (luma <= 8 || luma >= 247) {
                continue;
            }

            sums[0] += pixels.data[index];
            sums[1] += pixels.data[index + 1];
            sums[2] += pixels.data[index + 2];
            used += 1;
        }

        if (used > 0) {
            const means = sums.map((sum) => sum / used);
            const target = (means[0] + means[1] + means[2]) / 3;
            detected = means.map((mean, channel) => clamp(target / Math.max(mean, 1), 0.5, 2) * manual[channel]);
        }
    }

    const gains = detected.map((gain) => 1 + clamp(strength, 0, 1) * (gain - 1));

    for (let index = 0; index < pixels.data.length; index += 4) {
        pixels.data[index] *= gains[0];
        pixels.data[index + 1] *= gains[1];
        pixels.data[index + 2] *= gains[2];
    }
}

function applyContrast(pixels: PixelData, options: CorrectionSettings): void {
    const { method, strength } = options.contrast;
    const lut = new Uint8ClampedArray(256);
    let black = 0;
    let white = 255;

    if (method === "adaptive") {
        const sample = sampledLuminance(pixels.data);
        black = percentile(sample, clamp(options.contrast.low_percentile, 0, 100) / 100);
        white = percentile(sample, clamp(options.contrast.high_percentile, 0, 100) / 100);

        if (white - black < 1) {
            black = 0;
            white = 255;
        }
    }

    for (let value = 0; value < 256; value += 1) {
        const x = value / 255;
        const curved =
            method === "adaptive"
                ? clamp((value - black) / (white - black), 0, 1)
                : x * x * (3 - 2 * x);
        lut[value] = 255 * (x + clamp(strength, 0, 1) * (curved - x));
    }

    for (let index = 0; index < pixels.data.length; index += 4) {
        pixels.data[index] = lut[pixels.data[index]];
        pixels.data[index + 1] = lut[pixels.data[index + 1]];
        pixels.data[index + 2] = lut[pixels.data[index + 2]];
    }
}

function applyLocalContrast(pixels: PixelData, options: CorrectionSettings): void {
    const { tile_grid, strength } = options.localContrast;
    const count = pixels.width * pixels.height;
    const lightness = new Float32Array(count);

    for (let pixel = 0; pixel < count; pixel += 1) {
        lightness[pixel] = luminance(pixels.data, pixel * 4);
    }

    const radius = Math.max(2, Math.round(Math.min(pixels.width, pixels.height) / Math.max(1, tile_grid) / 2));
    const blurred = boxBlur(lightness, pixels.width, pixels.height, radius);

    for (let pixel = 0; pixel < count; pixel += 1) {
        const delta = clamp(strength, 0, 1) * (lightness[pixel] - blurred[pixel]);

        for (let channel = 0; channel < 3; channel += 1) {
            pixels.data[pixel * 4 + channel] += delta;
        }
    }
}

function applyVibrance(pixels: PixelData, options: CorrectionSettings): void {
    const strength = clamp(options.vibrance.strength, 0, 1);

    for (let index = 0; index < pixels.data.length; index += 4) {
        const r = pixels.data[index];
        const g = pixels.data[index + 1];
        const b = pixels.data[index + 2];
        const luma = 0.299 * r + 0.587 * g + 0.114 * b;
        const chroma = Math.max(r, g, b) - Math.min(r, g, b);
        const hueWeight = 1 - clamp(chroma / 128, 0, 1);
        const toneWeight = clamp(1 - Math.abs(2 * (luma / 255) - 1), 0, 1);
        const factor = 1 + strength * hueWeight * toneWeight;
        pixels.data[index] = luma + (r - luma) * factor;
        pixels.data[index + 1] = luma + (g - luma) * factor;
        pixels.data[index + 2] = luma + (b - luma) * factor;
    }
}

function applyNoiseReduction(pixels: PixelData, options: CorrectionSettings): void {
    const { method, radius, sigma_color, strength } = options.noiseReduction;
    const count = pixels.width * pixels.height;
    const blend =
        method === "nl_means" ? clamp(strength / 15, 0.1, 0.9) : clamp(sigma_color / 100, 0.1, 0.9);
    const blurRadius = Math.max(1, Math.round(radius / 2));

    for (let channel = 0; channel < 3; channel += 1) {
        const values = new Float32Array(count);

        for (let pixel = 0; pixel < count; pixel += 1) {
            values[pixel] = pixels.data[pixel * 4 + channel];
        }

        const blurred = boxBlur(values, pixels.width, pixels.height, blurRadius);

        for (let pixel = 0; pixel < count; pixel += 1) {
            pixels.data[pixel * 4 + channel] += blend * (blurred[pixel] - values[pixel]);
        }
    }
}

function applySharpening(pixels: PixelData, options: CorrectionSettings): void {
    const { radius, amount, threshold } = options.sharpening;
    const count = pixels.width * pixels.height;
    const blurRadius = Math.max(1, Math.round(radius * 2));

    for (let channel = 0; channel < 3; channel += 1) {
        const values = new Float32Array(count);

        for (let pixel = 0; pixel < count; pixel += 1) {
            values[pixel] = pixels.data[pixel * 4 + channel];
        }

        const blurred = boxBlur(values, pixels.width, pixels.height, blurRadius);

        for (let pixel = 0; pixel < count; pixel += 1) {
            let difference = values[pixel] - blurred[pixel];

            if (threshold > 0 && Math.abs(difference) <= threshold) {
                difference = 0;
            }

            pixels.data[pixel * 4 + channel] += clamp(amount, 0, 3) * difference;
        }
    }
}

/**
 * Applies the enabled corrections to preview pixels in the backend's chain order.
 *
 * This is deliberately an approximation: the browser uses box blurs and simple
 * colour models, while the backend uses OpenCV. It is fast enough to update on
 * every slider change; the saved file is always re-encoded by the backend.
 */
export function applyColorPreview(pixels: PixelData, options: CorrectionSettings): PixelData {
    const settings: CorrectionSettings = {
        exposure: effectiveCorrection("exposure", options.exposure),
        whiteBalance: effectiveCorrection("whiteBalance", options.whiteBalance),
        contrast: effectiveCorrection("contrast", options.contrast),
        localContrast: effectiveCorrection("localContrast", options.localContrast),
        vibrance: effectiveCorrection("vibrance", options.vibrance),
        noiseReduction: effectiveCorrection("noiseReduction", options.noiseReduction),
        sharpening: effectiveCorrection("sharpening", options.sharpening),
    };

    if (settings.exposure.enabled) {
        applyExposure(pixels, settings);
    }

    if (settings.whiteBalance.enabled) {
        applyWhiteBalance(pixels, settings);
    }

    if (settings.contrast.enabled) {
        applyContrast(pixels, settings);
    }

    if (settings.localContrast.enabled) {
        applyLocalContrast(pixels, settings);
    }

    if (settings.vibrance.enabled) {
        applyVibrance(pixels, settings);
    }

    if (settings.noiseReduction.enabled) {
        applyNoiseReduction(pixels, settings);
    }

    if (settings.sharpening.enabled) {
        applySharpening(pixels, settings);
    }

    return pixels;
}
