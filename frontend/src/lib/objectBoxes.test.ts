import { describe, expect, it } from "vitest";
import { objectRect } from "./objectBoxes";

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
