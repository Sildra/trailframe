import { normalizeProcessing } from "./processing";

export const MIN_TARGET_SIZE = 64;
export const MAX_TARGET_SIZE = 8192;
export const MAX_TARGETS = 5;
export const MAX_MANUAL_ANGLE = 45;
export const DEFAULT_MAIN_TARGET = 1080;

export type CorrectionMode = "off" | "automatic" | "manual";
export type TiltMode = "automatic" | "off" | "manual";
export type CropMode = "maximum_valid_rectangle" | "none";
export type CorrectionKey =
    | "exposure"
    | "whiteBalance"
    | "contrast"
    | "localContrast"
    | "vibrance"
    | "noiseReduction"
    | "sharpening";
export type PresetTarget = CorrectionKey | "tilt";

interface CorrectionBase {
    enabled: boolean;
    mode: CorrectionMode;
    preset: string;
}

export interface ExposureOptions extends CorrectionBase {
    exposure: number;
    gamma: number;
}

export interface WhiteBalanceOptions extends CorrectionBase {
    method: "gray_world" | "manual";
    strength: number;
    temperature: number;
    tint: number;
}

export interface ContrastOptions extends CorrectionBase {
    method: "s_curve" | "adaptive";
    strength: number;
    low_percentile: number;
    high_percentile: number;
}

export interface LocalContrastOptions extends CorrectionBase {
    clip_limit: number;
    tile_grid: number;
    strength: number;
}

export interface VibranceOptions extends CorrectionBase {
    strength: number;
}

export interface NoiseReductionOptions extends CorrectionBase {
    method: "bilateral" | "nl_means";
    radius: number;
    sigma_color: number;
    sigma_space: number;
    strength: number;
}

export interface SharpeningOptions extends CorrectionBase {
    radius: number;
    amount: number;
    threshold: number;
}

/** The state of the "Adjust processing" dialog. */
export interface ReprocessOptions {
    alternatives: number[];
    main: number;
    tiltMode: TiltMode;
    tiltPreset: string;
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

type CorrectionPayload = CorrectionBase;

export interface ReprocessPayload {
    alternatives: number[];
    main: number;
    tilt: { mode: string; preset: string; angle?: number; crop_mode: CropMode };
    exposure: CorrectionPayload & Pick<ExposureOptions, "exposure" | "gamma">;
    white_balance: CorrectionPayload &
        Pick<WhiteBalanceOptions, "method" | "strength" | "temperature" | "tint">;
    contrast: CorrectionPayload &
        Pick<ContrastOptions, "method" | "strength" | "low_percentile" | "high_percentile">;
    local_contrast: CorrectionPayload & Pick<LocalContrastOptions, "clip_limit" | "tile_grid" | "strength">;
    vibrance: CorrectionPayload & Pick<VibranceOptions, "strength">;
    noise_reduction: CorrectionPayload &
        Pick<NoiseReductionOptions, "method" | "radius" | "sigma_color" | "sigma_space" | "strength">;
    sharpening: CorrectionPayload & Pick<SharpeningOptions, "radius" | "amount" | "threshold">;
    rescan: boolean;
}

interface PresetDefinition {
    label: string;
    automatic: Record<string, unknown>;
    manual: Record<string, unknown>;
}

type PresetCatalogue = Record<PresetTarget, Record<string, PresetDefinition>>;

const preset = (label: string, automatic: Record<string, unknown>, manual = automatic): PresetDefinition => ({
    label,
    automatic,
    manual,
});

/** Named presets mirrored from the backend's `processors/presets.py`. */
export const PRESETS: PresetCatalogue = {
    exposure: {
        gentle: preset("Gentle", { exposure: 0.15, gamma: 1.02 }),
        balanced: preset("Balanced", { exposure: 0.3, gamma: 0.97 }, { exposure: 0, gamma: 1 }),
        strong: preset("Strong", { exposure: 0.6, gamma: 0.9 }),
    },
    whiteBalance: {
        neutral: preset("Neutral", {
            method: "gray_world",
            strength: 0.35,
            temperature: 0,
            tint: 0,
        }),
        warm: preset(
            "Warm",
            { method: "gray_world", strength: 0.45, temperature: 0.15, tint: 0.05 },
            { method: "manual", strength: 0.6, temperature: 0.25, tint: 0.05 },
        ),
        cool: preset(
            "Cool",
            { method: "gray_world", strength: 0.45, temperature: -0.15, tint: -0.05 },
            { method: "manual", strength: 0.6, temperature: -0.25, tint: -0.05 },
        ),
        shade: preset(
            "Shade",
            { method: "gray_world", strength: 0.7, temperature: 0.1, tint: 0 },
            { method: "gray_world", strength: 0.8, temperature: 0.1, tint: 0 },
        ),
    },
    contrast: {
        soft: preset(
            "Soft",
            { method: "adaptive", strength: 0.3, low_percentile: 8, high_percentile: 92 },
            { method: "s_curve", strength: 0.3, low_percentile: 8, high_percentile: 92 },
        ),
        standard: preset("Standard", {
            method: "adaptive",
            strength: 0.55,
            low_percentile: 5,
            high_percentile: 95,
        }),
        punchy: preset("Punchy", { method: "adaptive", strength: 0.8, low_percentile: 3, high_percentile: 97 }),
    },
    localContrast: {
        subtle: preset("Subtle", { clip_limit: 1, tile_grid: 8, strength: 0.3 }),
        standard: preset("Standard", { clip_limit: 2, tile_grid: 8, strength: 0.6 }),
        strong: preset("Strong", { clip_limit: 3.5, tile_grid: 8, strength: 0.9 }),
    },
    vibrance: {
        natural: preset("Natural", { strength: 0.25 }),
        vivid: preset("Vivid", { strength: 0.5 }),
        strong: preset("Strong", { strength: 0.8 }),
    },
    tilt: {
        conservative: preset(
            "Conservative",
            { min_confidence: 0.85, max_angle: 2.5, crop_mode: "maximum_valid_rectangle" },
            { crop_mode: "maximum_valid_rectangle" },
        ),
        standard: preset("Standard", { crop_mode: "maximum_valid_rectangle" }),
        assertive: preset(
            "Assertive",
            { min_confidence: 0.55, max_angle: 6, crop_mode: "maximum_valid_rectangle" },
            { crop_mode: "maximum_valid_rectangle" },
        ),
    },
    noiseReduction: {
        light: preset("Light", { method: "bilateral", radius: 3, sigma_color: 20, sigma_space: 20, strength: 4 }),
        standard: preset("Standard", {
            method: "bilateral",
            radius: 5,
            sigma_color: 35,
            sigma_space: 35,
            strength: 10,
        }),
        strong: preset("Strong", { method: "nl_means", radius: 5, sigma_color: 35, sigma_space: 35, strength: 14 }),
    },
    sharpening: {
        soft: preset("Soft", { radius: 1, amount: 0.3, threshold: 4 }),
        standard: preset("Standard", { radius: 1, amount: 0.5, threshold: 2 }),
        detail: preset("Detail", { radius: 1.2, amount: 0.9, threshold: 1 }),
    },
};

export const DEFAULT_PRESETS: Record<PresetTarget, string> = {
    exposure: "balanced",
    whiteBalance: "neutral",
    contrast: "standard",
    localContrast: "standard",
    vibrance: "natural",
    tilt: "standard",
    noiseReduction: "standard",
    sharpening: "standard",
};

export const CORRECTION_KEYS: CorrectionKey[] = [
    "exposure",
    "whiteBalance",
    "contrast",
    "localContrast",
    "vibrance",
    "noiseReduction",
    "sharpening",
];

export function presetKeys(target: PresetTarget): string[] {
    return Object.keys(PRESETS[target]);
}

export function presetLabel(target: PresetTarget, name: string): string {
    if (name === "custom") {
        return "Custom";
    }

    return PRESETS[target][name]?.label ?? name;
}

export function presetValues(target: PresetTarget, name: string, mode: CorrectionMode): Record<string, unknown> {
    if (name === "custom" || mode === "off") {
        return {};
    }

    return PRESETS[target][name]?.[mode] ?? {};
}

const DEFAULTS = {
    exposure: {
        enabled: false,
        mode: "off" as CorrectionMode,
        preset: DEFAULT_PRESETS.exposure,
        exposure: 0,
        gamma: 1,
    } satisfies ExposureOptions,
    whiteBalance: {
        enabled: false,
        mode: "off" as CorrectionMode,
        preset: DEFAULT_PRESETS.whiteBalance,
        method: "gray_world" as const,
        strength: 0.6,
        temperature: 0,
        tint: 0,
    } satisfies WhiteBalanceOptions,
    contrast: {
        enabled: false,
        mode: "off" as CorrectionMode,
        preset: DEFAULT_PRESETS.contrast,
        method: "s_curve" as const,
        strength: 0.5,
        low_percentile: 5,
        high_percentile: 95,
    } satisfies ContrastOptions,
    localContrast: {
        enabled: false,
        mode: "off" as CorrectionMode,
        preset: DEFAULT_PRESETS.localContrast,
        clip_limit: 2,
        tile_grid: 8,
        strength: 1,
    } satisfies LocalContrastOptions,
    vibrance: {
        enabled: false,
        mode: "off" as CorrectionMode,
        preset: DEFAULT_PRESETS.vibrance,
        strength: 0.4,
    } satisfies VibranceOptions,
    noiseReduction: {
        enabled: false,
        mode: "off" as CorrectionMode,
        preset: DEFAULT_PRESETS.noiseReduction,
        method: "bilateral" as const,
        radius: 5,
        sigma_color: 35,
        sigma_space: 35,
        strength: 10,
    } satisfies NoiseReductionOptions,
    sharpening: {
        enabled: false,
        mode: "off" as CorrectionMode,
        preset: DEFAULT_PRESETS.sharpening,
        radius: 1,
        amount: 0.5,
        threshold: 2,
    } satisfies SharpeningOptions,
};

function correctionMeta(
    steps: ReturnType<typeof normalizeProcessing>,
    step: string,
): Record<string, unknown> | null {
    return steps.find((entry) => entry.step === step)?.meta ?? null;
}

function storedMode(meta: Record<string, unknown> | null): CorrectionMode | null {
    const value = meta?.mode;

    if (value === "auto" || value === "automatic") {
        return "automatic";
    }

    return value === "off" || value === "manual" ? value : null;
}

function storedValues(base: Record<string, unknown>, meta: Record<string, unknown> | null): Record<string, unknown> {
    if (!meta) {
        return {};
    }

    const skip = new Set(["enabled", "mode", "preset", "applied"]);
    const values: Record<string, unknown> = {};

    for (const [key, fallback] of Object.entries(base)) {
        if (skip.has(key)) {
            continue;
        }

        const value = meta[key];

        if (typeof value === typeof fallback) {
            values[key] = value;
        }
    }

    return values;
}

function correctionFromMeta<K extends CorrectionKey>(
    key: K,
    meta: Record<string, unknown> | null,
    fallback: ReprocessOptions[K],
): ReprocessOptions[K] {
    const explicitMode = storedMode(meta);
    const mode: CorrectionMode = explicitMode ?? (meta ? (meta.applied === false ? "off" : "manual") : "off");
    const validPreset =
        typeof meta?.preset === "string" && (meta.preset === "custom" || PRESETS[key][meta.preset]);
    const named = validPreset ? (meta?.preset as string) : DEFAULT_PRESETS[key];
    // Legacy steps have no mode/preset: preserve their exact settings as a
    // manual custom recipe. `custom` is not valid in automatic or off mode.
    const preset =
        mode === "manual" && (explicitMode === null || named === "custom")
            ? "custom"
            : named === "custom"
              ? DEFAULT_PRESETS[key]
              : named;

    // Automatic mode is authoritative: the named preset wins over any values
    // captured in the recipe. Manual mode restores the actual edited values.
    const values = mode === "manual" ? storedValues(fallback as unknown as Record<string, unknown>, meta) : {};

    return {
        ...fallback,
        ...presetValues(key, preset, mode),
        ...values,
        mode,
        preset,
        enabled: mode !== "off",
    } as ReprocessOptions[K];
}

/**
 * The settings a processor actually uses. Automatic mode takes its values from
 * the named preset, never from the editable (hidden) client fields.
 */
export function effectiveCorrection<K extends CorrectionKey>(
    key: K,
    correction: ReprocessOptions[K],
): ReprocessOptions[K] {
    if (correction.mode === "off") {
        return { ...correction, enabled: false };
    }

    if (correction.mode === "automatic" && correction.preset !== "custom") {
        return {
            ...correction,
            ...presetValues(key, correction.preset, "automatic"),
            enabled: true,
        };
    }

    return { ...correction, enabled: true };
}

export function applyCorrectionMode<K extends CorrectionKey>(
    options: ReprocessOptions,
    key: K,
    mode: CorrectionMode,
): ReprocessOptions {
    const current = options[key];
    const presetName = current.preset === "custom" ? DEFAULT_PRESETS[key] : current.preset;

    return {
        ...options,
        [key]: {
            ...current,
            ...presetValues(key, presetName, mode),
            mode,
            preset: presetName,
            enabled: mode !== "off",
        },
    };
}

export function applyCorrectionPreset<K extends CorrectionKey>(
    options: ReprocessOptions,
    key: K,
    presetName: string,
): ReprocessOptions {
    const current = options[key];

    return {
        ...options,
        [key]: {
            ...current,
            ...presetValues(key, presetName, current.mode),
            preset: presetName,
            enabled: current.mode !== "off",
        },
    };
}

export function applyTiltMode(options: ReprocessOptions, mode: TiltMode): ReprocessOptions {
    const presetName = options.tiltPreset === "custom" ? DEFAULT_PRESETS.tilt : options.tiltPreset;
    const values = presetValues("tilt", presetName, mode === "automatic" ? "automatic" : "manual");
    const crop = values.crop_mode;

    return {
        ...options,
        tiltMode: mode,
        tiltPreset: presetName,
        cropMode: crop === "none" ? "none" : options.cropMode,
    };
}

export function applyTiltPreset(options: ReprocessOptions, presetName: string): ReprocessOptions {
    const values = presetValues(
        "tilt",
        presetName,
        options.tiltMode === "automatic" ? "automatic" : "manual",
    );
    const crop = values.crop_mode;

    return {
        ...options,
        tiltPreset: presetName,
        cropMode: crop === "none" ? "none" : options.cropMode,
    };
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
    const tiltMeta = tilt?.meta ?? null;
    const storedTiltMode = storedMode(tiltMeta);
    const tiltMode: TiltMode =
        storedTiltMode ?? (tiltMeta ? (tiltMeta.applied === false ? "off" : "manual") : "automatic");
    const storedTiltPreset = typeof tiltMeta?.preset === "string" ? tiltMeta.preset : null;
    const namedTiltPreset =
        storedTiltPreset && PRESETS.tilt[storedTiltPreset] ? storedTiltPreset : DEFAULT_PRESETS.tilt;
    const tiltPreset =
        tiltMode === "manual" && (storedTiltMode === null || storedTiltPreset === "custom")
            ? "custom"
            : namedTiltPreset;
    const angle = tilt ? (parseAngle(tilt.summary) ?? 0) : 0;

    return {
        alternatives: alternatives.length > 0 ? alternatives : [main],
        main,
        tiltMode,
        tiltPreset,
        angle,
        cropMode: tilt?.meta.crop_mode === "none" ? "none" : "maximum_valid_rectangle",
        exposure: correctionFromMeta("exposure", correctionMeta(steps, "exposure"), DEFAULTS.exposure),
        whiteBalance: correctionFromMeta(
            "whiteBalance",
            correctionMeta(steps, "white_balance"),
            DEFAULTS.whiteBalance,
        ),
        contrast: correctionFromMeta("contrast", correctionMeta(steps, "contrast"), DEFAULTS.contrast),
        localContrast: correctionFromMeta(
            "localContrast",
            correctionMeta(steps, "local_contrast"),
            DEFAULTS.localContrast,
        ),
        vibrance: correctionFromMeta("vibrance", correctionMeta(steps, "vibrance"), DEFAULTS.vibrance),
        noiseReduction: correctionFromMeta(
            "noiseReduction",
            correctionMeta(steps, "noise_reduction"),
            DEFAULTS.noiseReduction,
        ),
        sharpening: correctionFromMeta("sharpening", correctionMeta(steps, "sharpening"), DEFAULTS.sharpening),
        rescan: true,
    };
}

function inRange(value: number, min: number, max: number): boolean {
    return Number.isFinite(value) && value >= min && value <= max;
}

function correctionProblem<K extends CorrectionKey>(key: K, value: ReprocessOptions[K]): string | null {
    if (!["off", "automatic", "manual"].includes(value.mode)) {
        return `${key}: unknown correction mode.`;
    }

    if (value.mode !== "manual" && value.preset === "custom") {
        return `${key}: custom is only available in manual mode.`;
    }

    if (value.preset !== "custom" && !PRESETS[key][value.preset]) {
        return `${key}: unknown preset.`;
    }

    return null;
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

    for (const key of CORRECTION_KEYS) {
        const problem = correctionProblem(key, options[key]);

        if (problem) {
            return problem;
        }
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
            preset: options.tiltPreset,
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
