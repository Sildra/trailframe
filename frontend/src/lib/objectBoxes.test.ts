import { describe, expect, it } from "vitest";
import {
    confidenceOpacity,
    confidenceRegions,
    dedupeObjectBoxes,
    objectRect,
    type ObjectDetectionBox,
} from "./objectBoxes";

describe("objectRect", () => {
    it("matches the old behaviour when the served image has the reference size", () => {
        const rect = objectRect(
            { box: [10, 20, 110, 70], reference: { width: 200, height: 100 } },
            { nw: 200, nh: 100, scale: 2, ox: 5, oy: 7 },
        );

        expect(rect).toEqual({ x: 25, y: 47, width: 200, height: 100 });
    });

    it("scales a smaller reference up to a larger served image", () => {
        const rect = objectRect(
            { box: [0, 0, 50, 25], reference: { width: 100, height: 100 } },
            { nw: 200, nh: 200, scale: 1, ox: 0, oy: 0 },
        );

        expect(rect).toEqual({ x: 0, y: 0, width: 100, height: 50 });
    });

    it("maps X and Y independently for a different aspect ratio", () => {
        const rect = objectRect(
            { box: [10, 10, 110, 60], reference: { width: 200, height: 100 } },
            { nw: 400, nh: 100, scale: 1, ox: 0, oy: 0 },
        );

        // sx = 400 / 200 = 2, sy = 100 / 100 = 1
        expect(rect).toEqual({ x: 20, y: 10, width: 200, height: 50 });
    });

    it("returns null without a usable reference", () => {
        expect(
            objectRect(
                { box: [0, 0, 10, 10], reference: { width: 0, height: 0 } },
                { nw: 100, nh: 100, scale: 1, ox: 0, oy: 0 },
            ),
        ).toBeNull();
    });
});

describe("dedupeObjectBoxes", () => {
    it("keeps only the most confident near-identical box", () => {
        const boxes: ObjectDetectionBox[] = [
            { label: "dog", box: [0, 0, 100, 100], confidence: 0.55 },
            { label: "dog", box: [2, 1, 100, 100], confidence: 0.91 },
            { label: "dog", box: [0, 0, 100, 100], confidence: 0.7 },
        ];

        expect(dedupeObjectBoxes(boxes)).toEqual([
            { label: "dog", box: [2, 1, 100, 100], confidence: 0.91 },
        ]);
    });

    it("keeps boxes that only partially overlap", () => {
        const boxes: ObjectDetectionBox[] = [
            { label: "dog", box: [0, 0, 80, 80], confidence: 0.9 },
            { label: "cat", box: [60, 0, 100, 80], confidence: 0.5 },
        ];

        expect(dedupeObjectBoxes(boxes)).toHaveLength(2);
    });

    it("ignores boxes without four usable coordinates", () => {
        const boxes: ObjectDetectionBox[] = [
            { box: [0, 0, 10], confidence: 0.8 },
            { box: [0, 0, 0, 10], confidence: 0.8 },
            { box: [0, 0, 10, 10], confidence: 0.8 },
        ];

        expect(dedupeObjectBoxes(boxes)).toEqual([{ box: [0, 0, 10, 10], confidence: 0.8 }]);
    });
});

describe("confidenceRegions", () => {
    it("uses the highest confidence in a partially overlapping area", () => {
        const regions = confidenceRegions([
            { label: "dog", box: [0, 0, 80, 80], confidence: 0.9 },
            { label: "cat", box: [60, 0, 100, 80], confidence: 0.5 },
        ]);

        const at = (x: number) =>
            regions.find((region) => region.box[0] <= x && x < region.box[2])?.confidence;

        expect(at(30)).toBe(0.9);
        expect(at(70)).toBe(0.9);
        expect(at(90)).toBe(0.5);
    });

    it("makes a single confidence fade with its percentage", () => {
        expect(confidenceOpacity(1)).toBeGreaterThan(confidenceOpacity(0.5));
        expect(confidenceOpacity(0.5)).toBeGreaterThan(confidenceOpacity(0));
    });
});
