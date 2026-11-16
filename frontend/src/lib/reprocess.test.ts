import { describe, expect, it } from "vitest";
import {
    defaultReprocessOptions,
    toReprocessPayload,
    validateOptions,
    type ReprocessOptions,
} from "./reprocess";

function valid(options: Partial<ReprocessOptions> = {}): ReprocessOptions {
    return {
        alternatives: [640, 1080],
        main: 1080,
        tiltMode: "auto",
        angle: 0,
        cropMode: "maximum_valid_rectangle",
        rescan: true,
        ...options,
    };
}

describe("defaultReprocessOptions", () => {
    it("derives the sizes, main target and horizon from the photo", () => {
        const options = defaultReprocessOptions({
            alternatives: [
                { target_size: 1080, main: false },
                { target_size: 2048, main: true },
            ],
            processing: [
                {
                    step: "tilt",
                    summary: "-1.23°",
                    details: {},
                    meta: { crop_mode: "none" },
                },
            ],
        });

        expect(options.alternatives).toEqual([1080, 2048]);
        expect(options.main).toBe(2048);
        expect(options.tiltMode).toBe("auto");
        expect(options.angle).toBeCloseTo(-1.23);
        expect(options.cropMode).toBe("none");
        expect(options.rescan).toBe(true);
    });

    it("falls back to a default size and angle without alternatives or tilt", () => {
        const options = defaultReprocessOptions({ alternatives: [], processing: [] });

        expect(options.alternatives).toEqual([1080]);
        expect(options.main).toBe(1080);
        expect(options.angle).toBe(0);
        expect(options.cropMode).toBe("maximum_valid_rectangle");
    });

    it("picks the largest alternative as main when none is flagged", () => {
        const options = defaultReprocessOptions({ alternatives: [{ target_size: 320 }, { target_size: 640 }] });

        expect(options.main).toBe(640);
    });
});

describe("validateOptions", () => {
    it("accepts sensible options", () => {
        expect(validateOptions(valid())).toBeNull();
    });

    it("rejects an empty or oversized list", () => {
        expect(validateOptions(valid({ alternatives: [] }))).toContain("at least one");
        expect(validateOptions(valid({ alternatives: [64, 128, 256, 512, 1024, 2048], main: 1024 }))).toContain("At most");
    });

    it("rejects out-of-range sizes", () => {
        expect(validateOptions(valid({ alternatives: [16], main: 16 }))).toContain("between");
        expect(validateOptions(valid({ alternatives: [9000], main: 9000 }))).toContain("between");
        expect(validateOptions(valid({ alternatives: [1080.5], main: 1080.5 }))).toContain("between");
    });

    it("rejects a main size that is not generated", () => {
        expect(validateOptions(valid({ main: 320 }))).toContain("main size");
    });

    it("requires a sane manual angle", () => {
        expect(validateOptions(valid({ tiltMode: "manual", angle: 12.5 }))).toBeNull();
        expect(validateOptions(valid({ tiltMode: "manual", angle: 90 }))).toContain("manual angle");
        expect(validateOptions(valid({ tiltMode: "manual", angle: Number.NaN }))).toContain("manual angle");
    });
});

describe("toReprocessPayload", () => {
    it("sends sorted, deduplicated sizes and the tilt mode", () => {
        expect(toReprocessPayload(valid({ alternatives: [2048, 640, 640] }))).toEqual({
            alternatives: [640, 2048],
            main: 1080,
            tilt: { mode: "auto", crop_mode: "maximum_valid_rectangle" },
            rescan: true,
        });
    });

    it("only sends the angle for manual correction", () => {
        expect(toReprocessPayload(valid({ tiltMode: "manual", angle: -2.5 })).tilt).toEqual({
            mode: "manual",
            angle: -2.5,
            crop_mode: "maximum_valid_rectangle",
        });
        expect(toReprocessPayload(valid({ tiltMode: "off", angle: 3 })).tilt).toEqual({
            mode: "off",
            crop_mode: "maximum_valid_rectangle",
        });
    });
});
