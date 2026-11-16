import { normalizeProcessing } from "./processing";

export const MIN_TARGET_SIZE = 64;
export const MAX_TARGET_SIZE = 8192;
export const MAX_TARGETS = 5;
export const MAX_MANUAL_ANGLE = 45;
export const DEFAULT_MAIN_TARGET = 1080;

export type TiltMode = "auto" | "off" | "manual";
export type CropMode = "maximum_valid_rectangle" | "none";

/** The state of the "Adjust processing" dialog. */
export interface ReprocessOptions {
    alternatives: number[];
    main: number;
    tiltMode: TiltMode;
    angle: number;
    cropMode: CropMode;
    rescan: boolean;
}

export interface ReprocessAlternative {
    target_size?: number | null;
    main?: boolean;
}

export interface ReprocessPhoto {
    alternatives?: ReprocessAlternative[] | null;
    processing?: unknown[] | null;
}

export interface ReprocessPayload {
    alternatives: number[];
    main: number;
    tilt: { mode: TiltMode; angle?: number; crop_mode: CropMode };
    rescan: boolean;
}

function parseAngle(summary: string): number | null {
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

    const tilt = normalizeProcessing(photo.processing).find((step) => step.step === "tilt");
    const angle = tilt ? (parseAngle(tilt.summary) ?? 0) : 0;

    return {
        alternatives: alternatives.length > 0 ? alternatives : [main],
        main,
        tiltMode: "auto",
        angle,
        cropMode: tilt?.meta.crop_mode === "none" ? "none" : "maximum_valid_rectangle",
        rescan: true,
    };
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
        rescan: options.rescan,
    };
}
