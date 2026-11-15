import { describe, expect, it } from "vitest";
import { normalizeProcessing, stepLabel, tiltOverlay } from "./processing";

describe("normalizeProcessing", () => {
    it("keeps the details and meta blocks verbatim", () => {
        const steps = normalizeProcessing([
            {
                step: "tilt",
                summary: "-1.23°",
                details: { "Detection method": "hough", Confidence: "95%" },
                meta: { line: { x1: 0.1, y1: 0.4, x2: 0.9, y2: 0.5 } },
            },
        ]);

        expect(steps).toEqual([
            {
                step: "tilt",
                summary: "-1.23°",
                details: { "Detection method": "hough", Confidence: "95%" },
                meta: { line: { x1: 0.1, y1: 0.4, x2: 0.9, y2: 0.5 } },
            },
        ]);
    });

    it("drops detail values that are not strings", () => {
        const [step] = normalizeProcessing([{ step: "tilt", details: { Applied: "Yes", angle: 2.0 } }]);

        expect(step.details).toEqual({ Applied: "Yes" });
    });

    it("ignores unusable entries", () => {
        expect(normalizeProcessing([null, 42, "tilt"])).toEqual([]);
        expect(normalizeProcessing(undefined)).toEqual([]);
    });
});

describe("stepLabel", () => {
    it("capitalizes the step name", () => {
        expect(stepLabel("downscale")).toBe("Downscale");
        expect(stepLabel("")).toBe("Processing");
    });
});

describe("tiltOverlay", () => {
    it("returns the line and its reference point from meta", () => {
        const [step] = normalizeProcessing([
            {
                step: "tilt",
                summary: "-1.00°",
                details: {},
                meta: { line: { x1: 0.1, y1: 0.4, x2: 0.9, y2: 0.6 }, reference_point: { x: 0.5, y: 0.5 } },
            },
        ]);

        expect(tiltOverlay(step)).toEqual({
            line: { x1: 0.1, y1: 0.4, x2: 0.9, y2: 0.6 },
            reference: { x: 0.5, y: 0.5 },
        });
    });

    it("falls back to the line midpoint", () => {
        const [step] = normalizeProcessing([
            { step: "tilt", meta: { line: { x1: 0.2, y1: 0.2, x2: 0.6, y2: 0.4 } } },
        ]);
        const reference = tiltOverlay(step)?.reference;

        expect(reference?.x).toBeCloseTo(0.4);
        expect(reference?.y).toBeCloseTo(0.3);
    });

    it("only applies to tilt steps", () => {
        const [step] = normalizeProcessing([
            { step: "downscale", meta: { line: { x1: 0, y1: 0, x2: 1, y2: 0 } } },
        ]);

        expect(tiltOverlay(step)).toBeNull();
    });

    it("returns null without a usable line", () => {
        const [step] = normalizeProcessing([{ step: "tilt", meta: {} }]);

        expect(tiltOverlay(step)).toBeNull();
    });
});
