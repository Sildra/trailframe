import { describe, expect, it } from "vitest";
import { applyColorPreview, type PixelData } from "./colorPreview";
import { defaultReprocessOptions, type ReprocessOptions } from "./reprocess";

function image(width: number, height: number, colour: [number, number, number]): PixelData {
    const data = new Uint8ClampedArray(width * height * 4);

    for (let index = 0; index < width * height; index += 1) {
        data[index * 4] = colour[0];
        data[index * 4 + 1] = colour[1];
        data[index * 4 + 2] = colour[2];
        data[index * 4 + 3] = 255;
    }

    return { width, height, data };
}

function optionsWith(patch: (options: ReprocessOptions) => void): ReprocessOptions {
    const options = defaultReprocessOptions({});
    patch(options);
    return options;
}

function average(pixels: PixelData, channel: number): number {
    let sum = 0;
    const count = pixels.data.length / 4;

    for (let index = 0; index < count; index += 1) {
        sum += pixels.data[index * 4 + channel];
    }

    return sum / count;
}

describe("applyColorPreview", () => {
    it("leaves pixels alone when every correction is off", () => {
        const pixels = image(8, 8, [100, 120, 140]);
        const before = Array.from(pixels.data);

        applyColorPreview(pixels, defaultReprocessOptions({}));

        expect(Array.from(pixels.data)).toEqual(before);
    });

    it("brightens with positive exposure", () => {
        const pixels = image(8, 8, [100, 100, 100]);
        const options = optionsWith((value) => {
            value.exposure = { enabled: true, exposure: 1, gamma: 1 };
        });

        applyColorPreview(pixels, options);

        expect(average(pixels, 0)).toBeGreaterThan(100);
    });

    it("warms with a positive temperature", () => {
        const pixels = image(8, 8, [100, 100, 100]);
        const options = optionsWith((value) => {
            value.whiteBalance = {
                enabled: true,
                method: "manual",
                strength: 1,
                temperature: 1,
                tint: 0,
            };
        });

        applyColorPreview(pixels, options);

        expect(average(pixels, 0)).toBeGreaterThan(average(pixels, 2));
    });

    it("boosts saturation of muted colours with vibrance", () => {
        const pixels = image(8, 8, [120, 100, 100]);
        const options = optionsWith((value) => {
            value.vibrance = { enabled: true, strength: 1 };
        });

        applyColorPreview(pixels, options);

        expect(average(pixels, 0) - average(pixels, 2)).toBeGreaterThan(20);
    });

    it("adds overshoot at an edge when sharpening", () => {
        const pixels = image(16, 16, [100, 100, 100]);

        for (let y = 0; y < 16; y += 1) {
            for (let x = 8; x < 16; x += 1) {
                const index = (y * 16 + x) * 4;
                pixels.data[index] = 140;
                pixels.data[index + 1] = 140;
                pixels.data[index + 2] = 140;
            }
        }

        const options = optionsWith((value) => {
            value.sharpening = { enabled: true, radius: 1, amount: 1, threshold: 0 };
        });

        applyColorPreview(pixels, options);

        expect(Math.min(...pixels.data.filter((_, index) => index % 4 === 0))).toBeLessThan(100);
        expect(Math.max(...pixels.data.filter((_, index) => index % 4 === 0))).toBeGreaterThan(140);
    });
});
