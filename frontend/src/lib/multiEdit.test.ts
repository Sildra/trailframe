import { describe, expect, it } from "vitest";
import { normalizeReprocessOptions, type NormalizablePhoto } from "./multiEdit";

function photo(id: number, processing: NormalizablePhoto["processing"]): NormalizablePhoto {
    return {
        id,
        filename: `${id}.jpg`,
        alternatives: [{ target_size: 1080, main: true }],
        processing,
    };
}

function correction(step: string, meta: Record<string, unknown>): Record<string, unknown> {
    return { step, summary: "Applied", details: {}, meta };
}

function tilt(summary: string, cropMode: string): Record<string, unknown> {
    return {
        step: "tilt",
        summary,
        details: {},
        meta: { crop_mode: cropMode, applied: true },
    };
}

describe("normalizeReprocessOptions", () => {
    it("copies a selected reference photo", () => {
        const photos = [
            photo(1, [correction("exposure", { exposure: 0, gamma: 1 })]),
            photo(2, [correction("exposure", { exposure: 1.5, gamma: 1.2, applied: true })]),
        ];

        const options = normalizeReprocessOptions(photos, "reference", 2);

        expect(options?.exposure).toEqual({ enabled: true, exposure: 1.5, gamma: 1.2 });
        expect(options?.alternatives).toEqual([1080]);
    });

    it("averages numeric settings and uses the most common choices in barycentric mode", () => {
        const photos = [
            photo(1, [
                correction("exposure", { exposure: 0, gamma: 1, applied: true }),
                correction("white_balance", { method: "manual", strength: 0.4, applied: true }),
                tilt("1°", "none"),
            ]),
            photo(2, [
                correction("exposure", { exposure: 2, gamma: 1.4, applied: true }),
                correction("white_balance", { method: "manual", strength: 0.8, applied: true }),
                tilt("3°", "maximum_valid_rectangle"),
            ]),
        ];

        const options = normalizeReprocessOptions(photos, "barycentric");

        expect(options?.exposure).toEqual({ enabled: true, exposure: 1, gamma: 1.2 });
        expect(options?.whiteBalance.method).toBe("manual");
        expect(options?.whiteBalance.strength).toBe(0.6);
        expect(options?.tiltMode).toBe("manual");
        expect(options?.angle).toBe(2);
        expect(options?.cropMode).toBe("none");
    });

    it("disables a correction unless a majority of the selection had it on", () => {
        const photos = [
            photo(1, [correction("vibrance", { strength: 0.8, applied: true })]),
            photo(2, []),
            photo(3, []),
        ];

        const options = normalizeReprocessOptions(photos, "barycentric");

        expect(options?.vibrance.enabled).toBe(false);
        expect(options?.vibrance.strength).toBe(0.8);
    });

    it("returns null for an empty selection", () => {
        expect(normalizeReprocessOptions([], "barycentric")).toBeNull();
    });
});
