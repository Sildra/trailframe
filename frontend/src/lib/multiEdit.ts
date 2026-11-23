import { normalizeProcessing } from "./processing";
import {
    MAX_MANUAL_ANGLE,
    defaultReprocessOptions,
    parseAngle,
    type CropMode,
    type ReprocessOptions,
    type ReprocessPhoto,
    type TiltMode,
} from "./reprocess";

export type NormalizationMode = "reference" | "barycentric";

export interface NormalizablePhoto extends ReprocessPhoto {
    id?: number | null;
    filename?: string | null;
}

interface CorrectionInfo {
    meta: Record<string, unknown> | null;
    enabled: boolean;
}

function stepMeta(photo: NormalizablePhoto, step: string): Record<string, unknown> | null {
    return normalizeProcessing(photo.processing).find((entry) => entry.step === step)?.meta ?? null;
}

function isEnabled(meta: Record<string, unknown> | null): boolean {
    return meta !== null && meta.applied !== false;
}

function info(photos: NormalizablePhoto[], step: string): CorrectionInfo[] {
    return photos.map((photo) => {
        const meta = stepMeta(photo, step);
        return { meta, enabled: isEnabled(meta) };
    });
}

function active(entries: CorrectionInfo[]): Record<string, unknown>[] {
    return entries.filter((entry) => entry.enabled).map((entry) => entry.meta ?? {});
}

function majorityEnabled(entries: CorrectionInfo[]): boolean {
    return entries.length > 0 && active(entries).length * 2 > entries.length;
}

function numberFrom(metas: Record<string, unknown>[], key: string, fallback: number): number {
    const values = metas
        .map((meta) => meta[key])
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value));

    return values.length > 0 ? values.reduce((sum, value) => sum + value, 0) / values.length : fallback;
}

function rounded(value: number, decimals = 2): number {
    const factor = 10 ** decimals;
    return Math.round(value * factor) / factor;
}

function integerFrom(metas: Record<string, unknown>[], key: string, fallback: number): number {
    return Math.round(numberFrom(metas, key, fallback));
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

function barycentricOptions(photos: NormalizablePhoto[]): ReprocessOptions {
    const base = defaultReprocessOptions(photos[0]);
    const exposure = active(info(photos, "exposure"));
    const whiteBalance = active(info(photos, "white_balance"));
    const contrast = active(info(photos, "contrast"));
    const localContrast = active(info(photos, "local_contrast"));
    const vibrance = active(info(photos, "vibrance"));
    const noiseReduction = active(info(photos, "noise_reduction"));
    const sharpening = active(info(photos, "sharpening"));

    const tiltInfo = photos.map((photo) => {
        const meta = stepMeta(photo, "tilt");
        const angle = meta ? parseAngle(normalizeProcessing(photo.processing).find((entry) => entry.step === "tilt")?.summary ?? "") : null;

        return { meta, angle, active: isEnabled(meta) };
    });
    const angles = tiltInfo
        .filter((entry) => entry.active && entry.angle !== null)
        .map((entry) => entry.angle as number);
    const cropModes = tiltInfo
        .filter((entry) => entry.meta)
        .map((entry) => (entry.meta?.crop_mode === "none" ? "none" : "maximum_valid_rectangle") as CropMode);

    const tiltMode: TiltMode = angles.length > 0 ? "manual" : base.tiltMode;
    const angle =
        angles.length > 0
            ? Math.max(-MAX_MANUAL_ANGLE, Math.min(MAX_MANUAL_ANGLE, rounded(numberFrom(angles.map((value) => ({ value })), "value", 0))))
            : base.angle;

    return {
        ...base,
        tiltMode,
        angle,
        cropMode: modeValue(cropModes, base.cropMode),
        exposure: {
            enabled: majorityEnabled(info(photos, "exposure")),
            exposure: rounded(numberFrom(exposure, "exposure", base.exposure.exposure)),
            gamma: rounded(numberFrom(exposure, "gamma", base.exposure.gamma)),
        },
        whiteBalance: {
            enabled: majorityEnabled(info(photos, "white_balance")),
            method: modeValue(
                whiteBalance.map((meta) => (meta.method === "manual" ? "manual" : "gray_world")),
                base.whiteBalance.method,
            ),
            strength: rounded(numberFrom(whiteBalance, "strength", base.whiteBalance.strength)),
            temperature: rounded(numberFrom(whiteBalance, "temperature", base.whiteBalance.temperature)),
            tint: rounded(numberFrom(whiteBalance, "tint", base.whiteBalance.tint)),
        },
        contrast: {
            enabled: majorityEnabled(info(photos, "contrast")),
            method: modeValue(
                contrast.map((meta) => (meta.method === "adaptive" ? "adaptive" : "s_curve")),
                base.contrast.method,
            ),
            strength: rounded(numberFrom(contrast, "strength", base.contrast.strength)),
            low_percentile: rounded(numberFrom(contrast, "low_percentile", base.contrast.low_percentile)),
            high_percentile: rounded(numberFrom(contrast, "high_percentile", base.contrast.high_percentile)),
        },
        localContrast: {
            enabled: majorityEnabled(info(photos, "local_contrast")),
            clip_limit: rounded(numberFrom(localContrast, "clip_limit", base.localContrast.clip_limit)),
            tile_grid: integerFrom(localContrast, "tile_grid", base.localContrast.tile_grid),
            strength: rounded(numberFrom(localContrast, "strength", base.localContrast.strength)),
        },
        vibrance: {
            enabled: majorityEnabled(info(photos, "vibrance")),
            strength: rounded(numberFrom(vibrance, "strength", base.vibrance.strength)),
        },
        noiseReduction: {
            enabled: majorityEnabled(info(photos, "noise_reduction")),
            method: modeValue(
                noiseReduction.map((meta) => (meta.method === "nl_means" ? "nl_means" : "bilateral")),
                base.noiseReduction.method,
            ),
            radius: integerFrom(noiseReduction, "radius", base.noiseReduction.radius),
            sigma_color: rounded(numberFrom(noiseReduction, "sigma_color", base.noiseReduction.sigma_color)),
            sigma_space: rounded(numberFrom(noiseReduction, "sigma_space", base.noiseReduction.sigma_space)),
            strength: rounded(numberFrom(noiseReduction, "strength", base.noiseReduction.strength)),
        },
        sharpening: {
            enabled: majorityEnabled(info(photos, "sharpening")),
            radius: rounded(numberFrom(sharpening, "radius", base.sharpening.radius)),
            amount: rounded(numberFrom(sharpening, "amount", base.sharpening.amount)),
            threshold: rounded(numberFrom(sharpening, "threshold", base.sharpening.threshold)),
        },
        rescan: true,
    };
}

/**
 * Builds the options shared by a multi-edit selection. Reference mode copies one
 * photo; barycentric mode averages numeric settings and picks the most common
 * method/mode across the photos that have the correction enabled.
 */
export function normalizeReprocessOptions(
    photos: NormalizablePhoto[],
    mode: NormalizationMode,
    referenceId?: number | null,
): ReprocessOptions | null {
    if (photos.length === 0) {
        return null;
    }

    const reference = photos.find((photo) => photo.id === referenceId) ?? photos[0];

    return mode === "reference" ? defaultReprocessOptions(reference) : barycentricOptions(photos);
}
