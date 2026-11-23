import { normalizeProcessing } from "./processing";

export const MIN_TARGET_SIZE = 64;
export const MAX_TARGET_SIZE = 8192;
export const MAX_TARGETS = 5;
export const MAX_MANUAL_ANGLE = 45;
export const DEFAULT_MAIN_TARGET = 1080;

export type TiltMode = "auto" | "off" | "manual";
export type CropMode = "maximum_valid_rectangle" | "none";
export type WhiteBalanceMethod = "gray_world" | "manual";
export type ContrastMethod = "s_curve" | "adaptive";
export type NoiseReductionMethod = "bilateral" | "nl_means";

export interface ExposureOptions {
    enabled: boolean;
    exposure: number;
    gamma: number;
}

export interface WhiteBalanceOptions {
    enabled: boolean;
    method: WhiteBalanceMethod;
    strength: number;
    temperature: number;
    tint: number;
}

export interface ContrastOptions {
    enabled: boolean;
    method: ContrastMethod;
    strength: number;
    low_percentile: number;
    high_percentile: number;
}

export interface LocalContrastOptions {
    enabled: boolean;
    clip_limit: number;
    tile_grid: number;
    strength: number;
}

export interface VibranceOptions {
    enabled: boolean;
    strength: number;
}

export interface NoiseReductionOptions {
    enabled: boolean;
    method: NoiseReductionMethod;
    radius: number;
    sigma_color: number;
    sigma_space: number;
    strength: number;
}

export interface SharpeningOptions {
    enabled: boolean;
    radius: number;
    amount: number;
    threshold: number;
}

/** The state of the "Adjust processing" dialog. */
export interface ReprocessOptions {
    alternatives: number[];
    main: number;
    tiltMode: TiltMode;
    angle: number;
    cropMode: CropMode;
    exposure: ExposureOptions;
    whiteBalance: WhiteBalanceOptions;
    contrast: ContrastOptions;
    localContrast: LocalContrastOptions;
    vibrance: VibranceOptions;
    noiseReduction: NoiseReductionOptions;
    sharpening: SharpeningOptions;
    rescan: boolean;
}

export interface ReprocessAlternative {
    target_size?: number | null;
    main?: boolean;
}

export type CorrectionSettings = Pick<
    ReprocessOptions,
    "exposure" | "whiteBalance" | "contrast" | "localContrast" | "vibrance" | "noiseReduction" | "sharpening"
>;

export interface ReprocessPhoto {
    alternatives?: ReprocessAlternative[] | null;
    processing?: unknown[] | null;
}

export interface ReprocessPayload {
    alternatives: number[];
    main: number;
    tilt: { mode: TiltMode; angle?: number; crop_mode: CropMode };
    exposure: ExposureOptions;
    white_balance: WhiteBalanceOptions;
    contrast: ContrastOptions;
    local_contrast: LocalContrastOptions;
    vibrance: VibranceOptions;
    noise_reduction: NoiseReductionOptions;
    sharpening: SharpeningOptions;
    rescan: boolean;
}

const DEFAULTS = {
    exposure: { enabled: false, exposure: 0, gamma: 1 } satisfies ExposureOptions,
    whiteBalance: {
        enabled: false,
        method: "gray_world",
        strength: 0.6,
        temperature: 0,
        tint: 0,
    } satisfies WhiteBalanceOptions,
    contrast: {
        enabled: false,
        method: "s_curve",
        strength: 0.5,
        low_percentile: 5,
        high_percentile: 95,
    } satisfies ContrastOptions,
    localContrast: { enabled: false, clip_limit: 2, tile_grid: 8, strength: 1 } satisfies LocalContrastOptions,
    vibrance: { enabled: false, strength: 0.4 } satisfies VibranceOptions,
    noiseReduction: {
        enabled: false,
        method: "bilateral",
        radius: 5,
        sigma_color: 35,
        sigma_space: 35,
        strength: 10,
    } satisfies NoiseReductionOptions,
    sharpening: { enabled: false, radius: 1, amount: 0.5, threshold: 2 } satisfies SharpeningOptions,
};

function metaNumber(meta: Record<string, unknown>, key: string, fallback: number): number {
    const value = meta[key];
    return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function correctionMeta(
    steps: ReturnType<typeof normalizeProcessing>,
    step: string,
): Record<string, unknown> | null {
    return steps.find((entry) => entry.step === step)?.meta ?? null;
}

function correctionEnabled(meta: Record<string, unknown> | null): boolean {
    return meta !== null && meta.applied !== false;
}

export function parseAngle(summary: string): number | null {
    const match = /^([+-]?\d+(?:\.\d+)?)°$/.exec(summary.trim());

    if (!match) {
        return null;
    }

    const angle = Number(match[1]);

    return Number.isFinite(angle) ? angle : null;
}

/** Builds the dialog state from the current alternatives and processing recipe. */
export function defaultReprocessOptions(photo: ReprocessPhoto): ReprocessOptions {
    const entries = photo.alternatives ?? [];
    const targets = entries
        .map((entry) => entry.target_size)
        .filter((size): size is number => typeof size === "number" && Number.isFinite(size));
    const alternatives = [...new Set(targets)].sort((a, b) => a - b);
    const mainEntry = entries.find((entry) => entry.main && typeof entry.target_size === "number");
    const main =
        mainEntry && typeof mainEntry.target_size === "number"
            ? mainEntry.target_size
            : (alternatives[alternatives.length - 1] ?? DEFAULT_MAIN_TARGET);

    const steps = normalizeProcessing(photo.processing);
    const tilt = steps.find((step) => step.step === "tilt");
    const angle = tilt ? (parseAngle(tilt.summary) ?? 0) : 0;

    const exposure = correctionMeta(steps, "exposure");
    const whiteBalance = correctionMeta(steps, "white_balance");
    const contrast = correctionMeta(steps, "contrast");
    const localContrast = correctionMeta(steps, "local_contrast");
    const vibrance = correctionMeta(steps, "vibrance");
    const noiseReduction = correctionMeta(steps, "noise_reduction");
    const sharpening = correctionMeta(steps, "sharpening");

    return {
        alternatives: alternatives.length > 0 ? alternatives : [main],
        main,
        tiltMode: "auto",
        angle,
        cropMode: tilt?.meta.crop_mode === "none" ? "none" : "maximum_valid_rectangle",
        exposure: {
            enabled: correctionEnabled(exposure),
            exposure: metaNumber(exposure ?? {}, "exposure", DEFAULTS.exposure.exposure),
            gamma: metaNumber(exposure ?? {}, "gamma", DEFAULTS.exposure.gamma),
        },
        whiteBalance: {
            enabled: correctionEnabled(whiteBalance),
            method: whiteBalance?.method === "manual" ? "manual" : "gray_world",
            strength: metaNumber(whiteBalance ?? {}, "strength", DEFAULTS.whiteBalance.strength),
            temperature: metaNumber(whiteBalance ?? {}, "temperature", DEFAULTS.whiteBalance.temperature),
            tint: metaNumber(whiteBalance ?? {}, "tint", DEFAULTS.whiteBalance.tint),
        },
        contrast: {
            enabled: correctionEnabled(contrast),
            method: contrast?.method === "adaptive" ? "adaptive" : "s_curve",
            strength: metaNumber(contrast ?? {}, "strength", DEFAULTS.contrast.strength),
            low_percentile: metaNumber(contrast ?? {}, "low_percentile", DEFAULTS.contrast.low_percentile),
            high_percentile: metaNumber(contrast ?? {}, "high_percentile", DEFAULTS.contrast.high_percentile),
        },
        localContrast: {
            enabled: correctionEnabled(localContrast),
            clip_limit: metaNumber(localContrast ?? {}, "clip_limit", DEFAULTS.localContrast.clip_limit),
            tile_grid: metaNumber(localContrast ?? {}, "tile_grid", DEFAULTS.localContrast.tile_grid),
            strength: metaNumber(localContrast ?? {}, "strength", DEFAULTS.localContrast.strength),
        },
        vibrance: {
            enabled: correctionEnabled(vibrance),
            strength: metaNumber(vibrance ?? {}, "strength", DEFAULTS.vibrance.strength),
        },
        noiseReduction: {
            enabled: correctionEnabled(noiseReduction),
            method: noiseReduction?.method === "nl_means" ? "nl_means" : "bilateral",
            radius: metaNumber(noiseReduction ?? {}, "radius", DEFAULTS.noiseReduction.radius),
            sigma_color: metaNumber(noiseReduction ?? {}, "sigma_color", DEFAULTS.noiseReduction.sigma_color),
            sigma_space: metaNumber(noiseReduction ?? {}, "sigma_space", DEFAULTS.noiseReduction.sigma_space),
            strength: metaNumber(noiseReduction ?? {}, "strength", DEFAULTS.noiseReduction.strength),
        },
        sharpening: {
            enabled: correctionEnabled(sharpening),
            radius: metaNumber(sharpening ?? {}, "radius", DEFAULTS.sharpening.radius),
            amount: metaNumber(sharpening ?? {}, "amount", DEFAULTS.sharpening.amount),
            threshold: metaNumber(sharpening ?? {}, "threshold", DEFAULTS.sharpening.threshold),
        },
        rescan: true,
    };
}

function inRange(value: number, min: number, max: number): boolean {
    return Number.isFinite(value) && value >= min && value <= max;
}

/** Returns the first blocking problem with the options, or null when they are valid. */
export function validateOptions(options: ReprocessOptions): string | null {
    const targets = [...new Set(options.alternatives)];

    if (targets.length === 0) {
        return "Choose at least one target size.";
    }

    if (targets.length > MAX_TARGETS) {
        return `At most ${MAX_TARGETS} target sizes can be generated.`;
    }

    for (const size of targets) {
        if (!Number.isInteger(size) || size < MIN_TARGET_SIZE || size > MAX_TARGET_SIZE) {
            return `Target sizes must be between ${MIN_TARGET_SIZE} and ${MAX_TARGET_SIZE} px.`;
        }
    }

    if (!targets.includes(options.main)) {
        return "The main size must be one of the generated sizes.";
    }

    if (options.tiltMode === "manual" && (!Number.isFinite(options.angle) || Math.abs(options.angle) > MAX_MANUAL_ANGLE)) {
        return `The manual angle must be within ±${MAX_MANUAL_ANGLE}°.`;
    }

    if (!inRange(options.exposure.exposure, -6, 6)) {
        return "Exposure must be between -6 and +6 EV.";
    }

    if (!inRange(options.exposure.gamma, 0.2, 5)) {
        return "Gamma must be between 0.2 and 5.";
    }

    if (!inRange(options.whiteBalance.strength, 0, 1)) {
        return "White balance strength must be between 0 and 100%.";
    }

    if (!inRange(options.whiteBalance.temperature, -1, 1) || !inRange(options.whiteBalance.tint, -1, 1)) {
        return "Temperature and tint must be between -1 and 1.";
    }

    if (!inRange(options.contrast.strength, 0, 1)) {
        return "Contrast strength must be between 0 and 100%.";
    }

    if (
        !inRange(options.contrast.low_percentile, 0, 100) ||
        !inRange(options.contrast.high_percentile, 0, 100) ||
        options.contrast.low_percentile >= options.contrast.high_percentile
    ) {
        return "Contrast percentiles must be between 0 and 100, with the low value first.";
    }

    if (!inRange(options.localContrast.clip_limit, 0.01, 20) || !inRange(options.localContrast.tile_grid, 1, 64)) {
        return "Local contrast clip limit and tile grid are out of range.";
    }

    if (!inRange(options.localContrast.strength, 0, 1) || !inRange(options.vibrance.strength, 0, 1)) {
        return "Strength values must be between 0 and 100%.";
    }

    if (
        !inRange(options.noiseReduction.radius, 1, 30) ||
        !inRange(options.noiseReduction.sigma_color, 1, 200) ||
        !inRange(options.noiseReduction.sigma_space, 1, 200) ||
        !inRange(options.noiseReduction.strength, 1, 30)
    ) {
        return "Noise reduction settings are out of range.";
    }

    if (
        !inRange(options.sharpening.radius, 0.1, 10) ||
        !inRange(options.sharpening.amount, 0, 3) ||
        !inRange(options.sharpening.threshold, 0, 50)
    ) {
        return "Sharpening settings are out of range.";
    }

    return null;
}

/** The request body sent to the reprocess endpoint. */
export function toReprocessPayload(options: ReprocessOptions): ReprocessPayload {
    return {
        alternatives: [...new Set(options.alternatives)].sort((a, b) => a - b),
        main: options.main,
        tilt: {
            mode: options.tiltMode,
            ...(options.tiltMode === "manual" ? { angle: options.angle } : {}),
            crop_mode: options.cropMode,
        },
        exposure: options.exposure,
        white_balance: options.whiteBalance,
        contrast: options.contrast,
        local_contrast: options.localContrast,
        vibrance: options.vibrance,
        noise_reduction: options.noiseReduction,
        sharpening: options.sharpening,
        rescan: options.rescan,
    };
}
