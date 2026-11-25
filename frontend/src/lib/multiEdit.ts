import {
    CORRECTION_KEYS,
    DEFAULT_PRESETS,
    MAX_MANUAL_ANGLE,
    PRESETS,
    defaultReprocessOptions,
    presetValues,
    type CorrectionKey,
    type CorrectionMode,
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

const NUMERIC_FIELDS: Record<CorrectionKey, string[]> = {
    exposure: ["exposure", "gamma"],
    whiteBalance: ["strength", "temperature", "tint"],
    contrast: ["strength", "low_percentile", "high_percentile"],
    localContrast: ["clip_limit", "tile_grid", "strength"],
    vibrance: ["strength"],
    noiseReduction: ["radius", "sigma_color", "sigma_space", "strength"],
    sharpening: ["radius", "amount", "threshold"],
};

const STRING_FIELDS: Partial<Record<CorrectionKey, string[]>> = {
    whiteBalance: ["method"],
    contrast: ["method"],
    noiseReduction: ["method"],
};

const INTEGER_FIELDS = new Set(["localContrast.tile_grid", "noiseReduction.radius"]);

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

function correctionOptions<K extends CorrectionKey>(key: K, entries: ReprocessOptions[]): ReprocessOptions[K] {
    const base = entries[0][key] as unknown as Record<string, unknown>;
    const active = entries.filter((entry) => entry[key].mode !== "off");
    const mode: CorrectionMode = majorityEnabled(entries.map((entry) => entry[key].mode !== "off"))
        ? modeValue(
              active.map((entry) => entry[key].mode),
              base.mode === "off" ? "manual" : (base.mode as CorrectionMode),
          )
        : "off";
    const named = entries
        .filter((entry) => entry[key].mode === mode && entry[key].preset !== "custom" && PRESETS[key][entry[key].preset])
        .map((entry) => entry[key].preset);
    const preset = modeValue(named, DEFAULT_PRESETS[key]);
    const manual = entries.filter((entry) => entry[key].mode === "manual");
    const values: Record<string, unknown> = mode === "automatic" ? { ...presetValues(key, preset, "automatic") } : {};

    if (mode === "manual") {
        for (const field of NUMERIC_FIELDS[key]) {
            const fallback = Number(base[field]);
            const collected = manual.map((entry) =>
                Number((entry[key] as unknown as Record<string, unknown>)[field]),
            );
            const computed = average(collected, fallback);
            values[field] = INTEGER_FIELDS.has(`${key}.${field}`) ? Math.round(computed) : computed;
        }

        for (const field of STRING_FIELDS[key] ?? []) {
            values[field] = modeValue(
                manual.map((entry) => String((entry[key] as unknown as Record<string, unknown>)[field])),
                String(base[field]),
            );
        }
    }

    const presetName =
        mode === "manual" && (named.length === 0 || manual.some((entry) => entry[key].preset === "custom"))
            ? "custom"
            : preset;

    return {
        ...base,
        ...values,
        mode,
        preset: presetName,
        enabled: mode !== "off",
    } as ReprocessOptions[K];
}

function barycentricOptions(options: ReprocessOptions[]): ReprocessOptions {
    const base = options[0];
    const angles = options
        .filter((entry) => entry.tiltMode === "manual" || entry.angle !== 0)
        .map((entry) => entry.angle);
    const tiltMode: TiltMode = angles.length > 0
        ? "manual"
        : modeValue(
              options.map((entry) => entry.tiltMode),
              base.tiltMode,
          );
    const angle = angles.length > 0
        ? Math.max(-MAX_MANUAL_ANGLE, Math.min(MAX_MANUAL_ANGLE, average(angles, base.angle)))
        : base.angle;
    const tiltPreset = angles.length > 0
        ? "custom"
        : modeValue(
              options.map((entry) => entry.tiltPreset),
              DEFAULT_PRESETS.tilt,
          );

    const merged = {} as ReprocessOptions;

    for (const key of CORRECTION_KEYS) {
        Object.assign(merged, { [key]: correctionOptions(key, options) });
    }

    return {
        ...base,
        ...merged,
        tiltMode,
        tiltPreset,
        angle,
        cropMode: angles.length > 0 ? base.cropMode : modeValue<CropMode>(
            options.map((entry) => entry.cropMode),
            base.cropMode,
        ),
        rescan: true,
    };
}

/**
 * Builds the options shared by a multi-edit selection. Local edits win over the
 * saved recipe: reference mode copies one photo, barycentric mode averages the
 * selection's manual settings and votes on its modes/presets.
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
