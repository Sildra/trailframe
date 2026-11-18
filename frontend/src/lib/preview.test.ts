import { describe, expect, it } from "vitest";
import {
    buildPreview,
    cropSize,
    effectiveAngle,
    largestInscribedRectangle,
    lineAngle,
    outputSize,
    rotatedSize,
    type PreviewTilt,
} from "./preview";

const tilt = (overrides: Partial<PreviewTilt> = {}): PreviewTilt => ({
    line: null,
    reference: null,
    detectedAngle: null,
    ...overrides,
});

describe("rotatedSize", () => {
    it("keeps the source size at 0°", () => {
        expect(rotatedSize(100, 50, 0)).toEqual({ width: 100, height: 50 });
    });

    it("swaps the axes at 90°", () => {
        const size = rotatedSize(100, 50, 90);
        expect(size.width).toBeCloseTo(50);
        expect(size.height).toBeCloseTo(100);
    });

    it("grows a square by √2 at 45°", () => {
        const size = rotatedSize(100, 100, 45);
        expect(size.width).toBeCloseTo(141.421);
        expect(size.height).toBeCloseTo(141.421);
    });
});

describe("largestInscribedRectangle", () => {
    it("returns the source size without a correction", () => {
        expect(largestInscribedRectangle(4000, 3000, 0)).toEqual({ width: 4000, height: 3000 });
    });

    it("shrinks both edges when the image is rotated", () => {
        const rect = largestInscribedRectangle(4000, 3000, 5);
        expect(rect.width).toBeLessThan(4000);
        expect(rect.height).toBeLessThan(3000);
        expect(rect.width).toBeGreaterThan(0);
        expect(rect.height).toBeGreaterThan(0);
    });

    it("stays inside the rotated canvas", () => {
        const canvas = rotatedSize(4000, 3000, 5);
        const rect = largestInscribedRectangle(4000, 3000, 5);
        expect(rect.width).toBeLessThanOrEqual(canvas.width);
        expect(rect.height).toBeLessThanOrEqual(canvas.height);
    });
});

describe("cropSize", () => {
    it("keeps the expanded canvas when the crop is disabled", () => {
        expect(cropSize(100, 50, 10, "none")).toEqual(rotatedSize(100, 50, 10));
    });

    it("uses the inscribed rectangle when the crop is enabled", () => {
        expect(cropSize(100, 50, 10, "maximum_valid_rectangle")).toEqual(
            largestInscribedRectangle(100, 50, 10),
        );
    });

    it("returns the source size at 0°", () => {
        expect(cropSize(100, 50, 0, "maximum_valid_rectangle")).toEqual({ width: 100, height: 50 });
    });
});

describe("outputSize", () => {
    it("scales the crop to the target longest edge", () => {
        expect(outputSize({ width: 1080, height: 806 }, 1080, 4032)).toEqual({ width: 1080, height: 806 });
    });

    it("scales a larger crop down to the target", () => {
        expect(outputSize({ width: 2160, height: 1612 }, 1080, 4032)).toEqual({ width: 1080, height: 806 });
    });

    it("never upscales a source smaller than the target", () => {
        expect(outputSize({ width: 400, height: 300 }, 1080, 400)).toEqual({ width: 400, height: 300 });
    });
});

describe("lineAngle", () => {
    it("is zero for a horizontal line", () => {
        expect(lineAngle({ x1: 0, y1: 0.5, x2: 1, y2: 0.5 }, { width: 200, height: 100 })).toBeCloseTo(0);
    });

    it("accounts for the image aspect ratio", () => {
        expect(lineAngle({ x1: 0, y1: 0, x2: 1, y2: 1 }, { width: 200, height: 100 })).toBeCloseTo(26.565, 3);
    });

    it("is negative for a line rising to the right", () => {
        expect(lineAngle({ x1: 0, y1: 1, x2: 1, y2: 0 }, { width: 100, height: 100 })).toBeCloseTo(-45);
    });
});

describe("effectiveAngle", () => {
    it("uses the detected angle in automatic mode when it was applied", () => {
        expect(effectiveAngle("auto", 0, -2, true)).toBe(-2);
    });

    it("applies nothing in automatic mode when the estimate was not applied", () => {
        expect(effectiveAngle("auto", 0, -2, false)).toBe(0);
    });

    it("uses the manual angle in manual mode", () => {
        expect(effectiveAngle("manual", 3.5, -2, true)).toBe(3.5);
    });

    it("applies nothing when off", () => {
        expect(effectiveAngle("off", 3.5, -2, true)).toBe(0);
    });
});

describe("buildPreview", () => {
    it("keeps the full source when nothing is corrected", () => {
        const model = buildPreview({ width: 4000, height: 3000 }, tilt(), {
            angle: 0,
            cropMode: "maximum_valid_rectangle",
            target: 1080,
        });

        expect(model.canvas).toEqual({ width: 4000, height: 3000 });
        expect(model.crop).toEqual({ x: 0, y: 0, width: 4000, height: 3000 });
        expect(model.trims).toBe(false);
        expect(model.cropSize).toEqual({ width: 4000, height: 3000 });
        expect(model.output).toEqual({ width: 1080, height: 810 });
        expect(model.marker).toEqual({ x: 2000, y: 1500 });
    });

    it("trims the rotated borders and reports the output size", () => {
        const model = buildPreview({ width: 4000, height: 3000 }, tilt(), {
            angle: 10,
            cropMode: "maximum_valid_rectangle",
            target: 1080,
        });

        expect(model.canvas.width).toBeGreaterThan(4000);
        expect(model.crop.width).toBeLessThan(4000);
        expect(model.crop.height).toBeLessThan(3000);
        expect(model.trims).toBe(true);
        expect(Math.max(model.output.width, model.output.height)).toBe(1080);
    });

    it("keeps the expanded canvas when the crop is disabled", () => {
        const model = buildPreview({ width: 4000, height: 3000 }, tilt(), {
            angle: 10,
            cropMode: "none",
            target: 1080,
        });

        expect(model.crop).toEqual({ x: 0, y: 0, width: model.canvas.width, height: model.canvas.height });
        expect(model.cropSize).toEqual({
            width: Math.round(model.canvas.width),
            height: Math.round(model.canvas.height),
        });
        expect(model.trims).toBe(false);
    });

    it("draws the horizon through the reference point and levels it on the canvas", () => {
        const model = buildPreview(
            { width: 100, height: 100 },
            tilt({ reference: { x: 0.25, y: 0.75 }, detectedAngle: 0 }),
            { angle: 0, cropMode: "maximum_valid_rectangle", target: 100 },
        );

        expect(model.marker).toEqual({ x: 25, y: 75 });
        expect(model.level?.y1).toBeCloseTo(75);
        expect(model.level?.y2).toBeCloseTo(75);
        // The horizon is centered on the reference, in centered image coordinates.
        expect(model.horizon).not.toBeNull();
        expect((model.horizon!.x1 + model.horizon!.x2) / 2).toBeCloseTo(-25);
        expect((model.horizon!.y1 + model.horizon!.y2) / 2).toBeCloseTo(25);
    });

    it("rotates the reference marker with the photo", () => {
        const model = buildPreview(
            { width: 100, height: 100 },
            tilt({ reference: { x: 1, y: 1 } }),
            { angle: 90, cropMode: "maximum_valid_rectangle", target: 100 },
        );

        expect(model.marker?.x).toBeCloseTo(100);
        expect(model.marker?.y).toBeCloseTo(0);
    });

    it("has no horizon without a line or estimate", () => {
        const model = buildPreview({ width: 100, height: 100 }, tilt(), {
            angle: 0,
            cropMode: "maximum_valid_rectangle",
            target: 100,
        });

        expect(model.horizon).toBeNull();
        expect(model.marker).toEqual({ x: 50, y: 50 });
    });
});
