import {
    MAX_MANUAL_ANGLE,
    defaultReprocessOptions,
    type CropMode,
    type ReprocessOptions,
    type ReprocessPhoto,
    type TiltMode,
} from "./reprocess";

export type NormalizationMode = "reference" | "barycentric";

export interface NormalizablePhoto extends ReprocessPhoto {
    id?: number | null;
    filename?: string | null;
    date?: string | null;
}

interface Timestamped {
    date?: string | null;
    id?: number | null;
}

/** Chronological order, independent of similarity score. */
export function sortPhotosByTime<T extends Timestamped>(photos: T[]): T[] {
    return [...photos].sort((left, right) => {
        const leftDate = left.date ?? "\uffff";
        const rightDate = right.date ?? "\uffff";
        return leftDate.localeCompare(rightDate) || (left.id ?? 0) - (right.id ?? 0);
    });
}

/** Deep copy so applying one recipe to several photos does not share nested edits. */
export function cloneReprocessOptions(options: ReprocessOptions): ReprocessOptions {
    return JSON.parse(JSON.stringify(options)) as ReprocessOptions;
}

/** True when the local editor state differs from the photo's saved recipe. */
export function isEdited(photo: ReprocessPhoto, options: ReprocessOptions): boolean {
    return JSON.stringify(options) !== JSON.stringify(defaultReprocessOptions(photo));
}

function rounded(value: number, decimals = 2): number {
    const factor = 10 ** decimals;
    return Math.round(value * factor) / factor;
}

function average(values: number[], fallback: number): number {
    const finite = values.filter((value) => Number.isFinite(value));
    return finite.length > 0 ? rounded(finite.reduce((sum, value) => sum + value, 0) / finite.length) : fallback;
}

function roundedInteger(values: number[], fallback: number): number {
    return Math.round(average(values, fallback));
}

function majorityEnabled(values: boolean[]): boolean {
    return values.length > 0 && values.filter(Boolean).length * 2 > values.length;
}

function modeValue<T extends string>(values: T[], fallback: T): T {
    const counts = new Map<T, number>();

    for (const value of values) {
        counts.set(value, (counts.get(value) ?? 0) + 1);
    }

    let best = fallback;
    let bestCount = counts.get(fallback) ?? 0;

    for (const [value, count] of counts) {
        if (count > bestCount || (count === bestCount && value === fallback)) {
            best = value;
            bestCount = count;
        }
    }

    return best;
}

function barycentricOptions(options: ReprocessOptions[]): ReprocessOptions {
    const base = options[0];
    const exposure = options.filter((entry) => entry.exposure.enabled).map((entry) => entry.exposure);
    const whiteBalance = options.filter((entry) => entry.whiteBalance.enabled).map((entry) => entry.whiteBalance);
    const contrast = options.filter((entry) => entry.contrast.enabled).map((entry) => entry.contrast);
    const localContrast = options.filter((entry) => entry.localContrast.enabled).map((entry) => entry.localContrast);
    const vibrance = options.filter((entry) => entry.vibrance.enabled).map((entry) => entry.vibrance);
    const noiseReduction = options.filter((entry) => entry.noiseReduction.enabled).map((entry) => entry.noiseReduction);
    const sharpening = options.filter((entry) => entry.sharpening.enabled).map((entry) => entry.sharpening);

    const angles = options
        .filter((entry) => entry.tiltMode === "manual" || entry.angle !== 0)
        .map((entry) => entry.angle);
    const tiltMode: TiltMode = angles.length > 0 ? "manual" : base.tiltMode;
    const angle = angles.length > 0
        ? Math.max(-MAX_MANUAL_ANGLE, Math.min(MAX_MANUAL_ANGLE, average(angles, base.angle)))
        : base.angle;

    return {
        ...base,
        tiltMode,
        angle,
        cropMode: modeValue<CropMode>(
            options.map((entry) => entry.cropMode),
            base.cropMode,
        ),
        exposure: {
            enabled: majorityEnabled(options.map((entry) => entry.exposure.enabled)),
            exposure: average(exposure.map((entry) => entry.exposure), base.exposure.exposure),
            gamma: average(exposure.map((entry) => entry.gamma), base.exposure.gamma),
        },
        whiteBalance: {
            enabled: majorityEnabled(options.map((entry) => entry.whiteBalance.enabled)),
            method: modeValue(
                whiteBalance.map((entry) => entry.method),
                base.whiteBalance.method,
            ),
            strength: average(whiteBalance.map((entry) => entry.strength), base.whiteBalance.strength),
            temperature: average(whiteBalance.map((entry) => entry.temperature), base.whiteBalance.temperature),
            tint: average(whiteBalance.map((entry) => entry.tint), base.whiteBalance.tint),
        },
        contrast: {
            enabled: majorityEnabled(options.map((entry) => entry.contrast.enabled)),
            method: modeValue(
                contrast.map((entry) => entry.method),
                base.contrast.method,
            ),
            strength: average(contrast.map((entry) => entry.strength), base.contrast.strength),
            low_percentile: average(contrast.map((entry) => entry.low_percentile), base.contrast.low_percentile),
            high_percentile: average(contrast.map((entry) => entry.high_percentile), base.contrast.high_percentile),
        },
        localContrast: {
            enabled: majorityEnabled(options.map((entry) => entry.localContrast.enabled)),
            clip_limit: average(localContrast.map((entry) => entry.clip_limit), base.localContrast.clip_limit),
            tile_grid: roundedInteger(localContrast.map((entry) => entry.tile_grid), base.localContrast.tile_grid),
            strength: average(localContrast.map((entry) => entry.strength), base.localContrast.strength),
        },
        vibrance: {
            enabled: majorityEnabled(options.map((entry) => entry.vibrance.enabled)),
            strength: average(vibrance.map((entry) => entry.strength), base.vibrance.strength),
        },
        noiseReduction: {
            enabled: majorityEnabled(options.map((entry) => entry.noiseReduction.enabled)),
            method: modeValue(
                noiseReduction.map((entry) => entry.method),
                base.noiseReduction.method,
            ),
            radius: roundedInteger(noiseReduction.map((entry) => entry.radius), base.noiseReduction.radius),
            sigma_color: average(noiseReduction.map((entry) => entry.sigma_color), base.noiseReduction.sigma_color),
            sigma_space: average(noiseReduction.map((entry) => entry.sigma_space), base.noiseReduction.sigma_space),
            strength: average(noiseReduction.map((entry) => entry.strength), base.noiseReduction.strength),
        },
        sharpening: {
            enabled: majorityEnabled(options.map((entry) => entry.sharpening.enabled)),
            radius: average(sharpening.map((entry) => entry.radius), base.sharpening.radius),
            amount: average(sharpening.map((entry) => entry.amount), base.sharpening.amount),
            threshold: average(sharpening.map((entry) => entry.threshold), base.sharpening.threshold),
        },
        rescan: true,
    };
}

/**
 * Builds the options shared by a multi-edit selection. Local edits win over the
 * saved recipe: reference mode copies one photo, barycentric mode averages the
 * selection's numeric settings and picks the most common methods and modes.
 */
export function normalizeReprocessOptions(
    photos: NormalizablePhoto[],
    mode: NormalizationMode,
    referenceId?: number | null,
    optionsById?: Record<number, ReprocessOptions>,
): ReprocessOptions | null {
    if (photos.length === 0) {
        return null;
    }

    const localOptions = (photo: NormalizablePhoto) =>
        photo.id != null ? optionsById?.[photo.id] : undefined;

    if (mode === "reference") {
        const reference = photos.find((photo) => photo.id === referenceId) ?? photos[0];
        return cloneReprocessOptions(localOptions(reference) ?? defaultReprocessOptions(reference));
    }

    return barycentricOptions(
        photos.map((photo) => localOptions(photo) ?? defaultReprocessOptions(photo)),
    );
}
