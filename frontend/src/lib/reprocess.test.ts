import { describe, expect, it } from "vitest";
import {
    applyCorrectionMode,
    applyCorrectionPreset,
    defaultReprocessOptions,
    effectiveCorrection,
    toReprocessPayload,
    validateOptions,
    type ReprocessOptions,
} from "./reprocess";

function valid(options: Partial<ReprocessOptions> = {}): ReprocessOptions {
    return {
        ...defaultReprocessOptions({}),
        alternatives: [640, 1080],
        main: 1080,
        tiltMode: "automatic",
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
        expect(options.tiltMode).toBe("manual");
        expect(options.tiltPreset).toBe("custom");
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

    it("treats legacy steps as manual custom recipes", () => {
        const options = defaultReprocessOptions({
            processing: [
                {
                    step: "exposure",
                    summary: "",
                    details: {},
                    meta: { exposure: 0.5, gamma: 1.2 },
                },
                {
                    step: "vibrance",
                    summary: "",
                    details: {},
                    meta: { strength: 0.8 },
                },
                {
                    step: "noise_reduction",
                    summary: "",
                    details: {},
                    meta: { method: "nl_means", strength: 7 },
                },
            ],
        });

        expect(options.exposure).toEqual({
            enabled: true,
            mode: "manual",
            preset: "custom",
            exposure: 0.5,
            gamma: 1.2,
        });
        expect(options.vibrance).toEqual({ enabled: true, mode: "manual", preset: "custom", strength: 0.8 });
        expect(options.noiseReduction.method).toBe("nl_means");
        expect(options.noiseReduction.strength).toBe(7);
        expect(options.sharpening.enabled).toBe(false);
    });

    it("uses the named preset's values in automatic mode", () => {
        const options = defaultReprocessOptions({
            processing: [
                {
                    step: "exposure",
                    summary: "",
                    details: {},
                    meta: { mode: "automatic", preset: "strong", exposure: 0, gamma: 1 },
                },
            ],
        });

        expect(options.exposure).toMatchObject({
            enabled: true,
            mode: "automatic",
            preset: "strong",
            exposure: 0.6,
            gamma: 0.9,
        });
    });

    it("treats a recorded skipped step as disabled", () => {
        const options = defaultReprocessOptions({
            processing: [
                {
                    step: "vibrance",
                    summary: "Not applied",
                    details: {},
                    meta: { applied: false },
                },
            ],
        });

        expect(options.vibrance.enabled).toBe(false);
        expect(options.vibrance.mode).toBe("off");
        expect(options.vibrance.strength).toBe(0.4);
    });
});

describe("mode and preset helpers", () => {
    it("applies preset values when the mode changes", () => {
        const options = valid();
        const automatic = applyCorrectionMode(options, "exposure", "automatic");

        expect(automatic.exposure).toMatchObject({ mode: "automatic", preset: "balanced", exposure: 0.3, gamma: 0.97 });

        const manual = applyCorrectionMode(automatic, "exposure", "manual");

        expect(manual.exposure).toMatchObject({ mode: "manual", preset: "balanced", exposure: 0, gamma: 1 });
    });

    it("fills editable values when a manual preset is selected", () => {
        const options = applyCorrectionMode(valid(), "vibrance", "manual");
        const vivid = applyCorrectionPreset(options, "vibrance", "vivid");

        expect(vivid.vibrance).toMatchObject({ mode: "manual", preset: "vivid", strength: 0.5 });
    });

    it("resolves automatic effective values independently of the editable fields", () => {
        const options = valid();
        const edited = {
            ...options,
            exposure: { ...options.exposure, mode: "automatic" as const, preset: "strong", exposure: 0, gamma: 1 },
        };

        expect(effectiveCorrection("exposure", edited.exposure)).toMatchObject({ exposure: 0.6, gamma: 0.9 });
        expect(effectiveCorrection("exposure", { ...edited.exposure, mode: "off" }).enabled).toBe(false);
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

    it("rejects an invalid mode or preset", () => {
        const unknownMode = valid();
        unknownMode.exposure = { ...unknownMode.exposure, mode: "sideways" as "manual" };
        expect(validateOptions(unknownMode)).toContain("unknown correction mode");

        const unknownPreset = valid();
        unknownPreset.exposure = { ...unknownPreset.exposure, mode: "manual", preset: "nope" };
        expect(validateOptions(unknownPreset)).toContain("unknown preset");

        const customAutomatic = valid();
        customAutomatic.exposure = { ...customAutomatic.exposure, mode: "automatic", preset: "custom" };
        expect(validateOptions(customAutomatic)).toContain("only available in manual mode");

        const customOff = valid();
        customOff.exposure = { ...customOff.exposure, mode: "off", preset: "custom" };
        expect(validateOptions(customOff)).toContain("only available in manual mode");
    });
});

describe("toReprocessPayload", () => {
    it("sends sorted, deduplicated sizes and the tilt mode", () => {
        const payload = toReprocessPayload(valid({ alternatives: [2048, 640, 640] }));

        expect(payload.alternatives).toEqual([640, 2048]);
        expect(payload.tilt).toEqual({
            mode: "automatic",
            preset: "standard",
            crop_mode: "maximum_valid_rectangle",
        });
        expect(payload.rescan).toBe(true);
    });

    it("sends every correction with its mode and preset", () => {
        const payload = toReprocessPayload(valid());

        expect(payload.exposure).toEqual({
            enabled: false,
            mode: "off",
            preset: "balanced",
            exposure: 0,
            gamma: 1,
        });
        expect(payload.white_balance).toMatchObject({ enabled: false, mode: "off", method: "gray_world" });
        expect(payload.contrast).toMatchObject({ enabled: false, mode: "off", method: "s_curve" });
        expect(payload.local_contrast).toMatchObject({ enabled: false, mode: "off", tile_grid: 8 });
        expect(payload.vibrance).toEqual({ enabled: false, mode: "off", preset: "natural", strength: 0.4 });
        expect(payload.noise_reduction).toMatchObject({ enabled: false, mode: "off", method: "bilateral" });
        expect(payload.sharpening).toMatchObject({ enabled: false, mode: "off", amount: 0.5 });
    });

    it("only sends the angle for manual correction", () => {
        expect(toReprocessPayload(valid({ tiltMode: "manual", angle: -2.5 })).tilt).toEqual({
            mode: "manual",
            preset: "standard",
            angle: -2.5,
            crop_mode: "maximum_valid_rectangle",
        });
        expect(toReprocessPayload(valid({ tiltMode: "off", angle: 3 })).tilt).toEqual({
            mode: "off",
            preset: "standard",
            crop_mode: "maximum_valid_rectangle",
        });
    });
});
