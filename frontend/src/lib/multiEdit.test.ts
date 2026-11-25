import { describe, expect, it } from "vitest";
import { defaultReprocessOptions } from "./reprocess";
import {
    isEdited,
    normalizeReprocessOptions,
    sortPhotosByTime,
    type NormalizablePhoto,
} from "./multiEdit";

function photo(id: number, processing: NormalizablePhoto["processing"]): NormalizablePhoto {
    return {
        id,
        filename: `${id}.jpg`,
        alternatives: [{ target_size: 1080, main: true }],
        processing,
    };
}

function correction(step: string, meta: Record<string, unknown>): Record<string, unknown> {
    return {
        step,
        summary: "Applied",
        details: {},
        meta: { mode: "manual", preset: "custom", applied: true, ...meta },
    };
}

function tilt(summary: string, cropMode: string): Record<string, unknown> {
    return {
        step: "tilt",
        summary,
        details: {},
        meta: { mode: "manual", preset: "custom", crop_mode: cropMode, applied: true },
    };
}

describe("normalizeReprocessOptions", () => {
    it("copies a selected reference photo", () => {
        const photos = [
            photo(1, [correction("exposure", { exposure: 0, gamma: 1 })]),
            photo(2, [correction("exposure", { exposure: 1.5, gamma: 1.2 })]),
        ];

        const options = normalizeReprocessOptions(photos, "reference", 2);

        expect(options?.exposure).toEqual({
            enabled: true,
            mode: "manual",
            preset: "custom",
            exposure: 1.5,
            gamma: 1.2,
        });
        expect(options?.alternatives).toEqual([1080]);
    });

    it("averages numeric settings and uses the most common choices in barycentric mode", () => {
        const photos = [
            photo(1, [
                correction("exposure", { exposure: 0, gamma: 1 }),
                correction("white_balance", { method: "manual", strength: 0.4 }),
                tilt("1°", "none"),
            ]),
            photo(2, [
                correction("exposure", { exposure: 2, gamma: 1.4 }),
                correction("white_balance", { method: "manual", strength: 0.8 }),
                tilt("3°", "maximum_valid_rectangle"),
            ]),
        ];

        const options = normalizeReprocessOptions(photos, "barycentric");

        expect(options?.exposure).toEqual({
            enabled: true,
            mode: "manual",
            preset: "custom",
            exposure: 1,
            gamma: 1.2,
        });
        expect(options?.whiteBalance.method).toBe("manual");
        expect(options?.whiteBalance.strength).toBe(0.6);
        expect(options?.tiltMode).toBe("manual");
        expect(options?.tiltPreset).toBe("custom");
        expect(options?.angle).toBe(2);
        expect(options?.cropMode).toBe("none");
    });

    it("votes on automatic presets without averaging their hidden settings", () => {
        const photos = [
            photo(1, [
                {
                    step: "exposure",
                    summary: "",
                    details: {},
                    meta: { mode: "automatic", preset: "strong", exposure: 0.6, gamma: 0.9 },
                },
            ]),
            photo(2, [
                {
                    step: "exposure",
                    summary: "",
                    details: {},
                    meta: { mode: "automatic", preset: "strong", exposure: 0.6, gamma: 0.9 },
                },
            ]),
            photo(3, [
                {
                    step: "exposure",
                    summary: "",
                    details: {},
                    meta: { mode: "automatic", preset: "gentle", exposure: 0.15, gamma: 1.02 },
                },
            ]),
        ];

        const options = normalizeReprocessOptions(photos, "barycentric");

        expect(options?.exposure).toMatchObject({ mode: "automatic", preset: "strong", exposure: 0.6, gamma: 0.9 });
    });

    it("disables a correction unless a majority of the selection had it on", () => {
        const photos = [
            photo(1, [correction("vibrance", { strength: 0.8 })]),
            photo(2, []),
            photo(3, []),
        ];

        const options = normalizeReprocessOptions(photos, "barycentric");

        expect(options?.vibrance).toMatchObject({ enabled: false, mode: "off", strength: 0.8 });
    });

    it("uses local edits for reference and barycentric normalization", () => {
        const photos = [photo(1, []), photo(2, [])];
        const edited = defaultReprocessOptions(photos[0]);
        edited.exposure = { ...edited.exposure, enabled: true, mode: "manual", preset: "custom", exposure: 2, gamma: 1.5 };
        const optionsById = { 1: edited };

        const reference = normalizeReprocessOptions(photos, "reference", 1, optionsById);
        expect(reference?.exposure).toEqual({
            enabled: true,
            mode: "manual",
            preset: "custom",
            exposure: 2,
            gamma: 1.5,
        });

        const barycentre = normalizeReprocessOptions(photos, "barycentric", undefined, optionsById);
        expect(barycentre?.exposure).toMatchObject({ enabled: false, mode: "off", exposure: 2 });
    });

    it("returns null for an empty selection", () => {
        expect(normalizeReprocessOptions([], "barycentric")).toBeNull();
    });
});

describe("editor helpers", () => {
    it("sorts photos by capture time", () => {
        const photos = [
            photo(1, []),
            { ...photo(2, []), date: "2024-05-01T10:00:00" },
            { ...photo(3, []), date: "2024-05-01T09:00:00" },
        ];

        expect(sortPhotosByTime(photos).map((entry) => entry.id)).toEqual([3, 2, 1]);
    });

    it("detects unsaved edits", () => {
        const selected = photo(1, []);
        const original = defaultReprocessOptions(selected);
        const edited = { ...original, vibrance: { ...original.vibrance, enabled: true, mode: "manual" as const } };

        expect(isEdited(selected, original)).toBe(false);
        expect(isEdited(selected, edited)).toBe(true);
    });
});
