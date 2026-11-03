import { describe, expect, it } from "vitest";
import { ensureUnit, typeCharacter } from "./typing";
import type { RuleSchema } from "./schema";

const SCHEMA: RuleSchema = {
    version: 1,
    capabilities: [],
    grammar: { keywords: [], operators: {} },
    detection: {
        path: "objects",
        label_field: "label",
        label_values: { source: "objects", values: [] },
        operators: ["present", "absent"],
        metrics: [
            {
                name: "confidence",
                label: "Confidence",
                description: "",
                kind: "number",
                operators: ["gte"],
                min: 0,
                max: 100,
                step: 1,
                unit: "%",
            },
        ],
    },
    groups: [
        {
            name: "Camera",
            label: "Camera",
            fields: [
                {
                    path: "exif.FNumber",
                    group: "Camera",
                    label: "Aperture",
                    description: "",
                    kind: "number",
                    operators: ["gte"],
                    computed: false,
                    values: { source: "none", values: [] },
                    min: 0,
                    max: 64,
                    step: 0.1,
                    unit: "f/",
                },
                {
                    path: "width",
                    group: "Image",
                    label: "Width",
                    description: "",
                    kind: "number",
                    operators: ["gte"],
                    computed: true,
                    values: { source: "none", values: [] },
                    min: 0,
                    step: 1,
                    unit: "px",
                },
            ],
        },
        {
            name: "File",
            label: "File",
            fields: [
                {
                    path: "filename",
                    group: "File",
                    label: "Filename",
                    description: "",
                    kind: "text",
                    operators: ["eq", "contains", "in"],
                    computed: false,
                    values: { source: "none", values: [] },
                },
            ],
        },
    ],
};

describe("ensureUnit", () => {
    it("appends a suffix unit while the number is typed", () => {
        const text = "width >= 12";

        expect(ensureUnit(SCHEMA, text, text.length)).toEqual({ text: "width >= 12px", caret: text.length });
    });

    it("puts a prefix unit in front of the number", () => {
        const text = "exif.FNumber >= 2.8";

        expect(ensureUnit(SCHEMA, text, text.length)).toEqual({ text: "exif.FNumber >= f/2.8", caret: text.length + 2 });
    });

    it("completes a metric with percent", () => {
        const text = 'objects has "dog" with confidence >= 80';

        expect(ensureUnit(SCHEMA, text, text.length)).toEqual({ text: `${text}%`, caret: text.length });
    });

    it("does not stack a unit when applied again", () => {
        const first = ensureUnit(SCHEMA, "width >= 12", 11);

        expect(first).toEqual({ text: "width >= 12px", caret: 11 });
        expect(ensureUnit(SCHEMA, first?.text ?? "", first?.caret ?? 0)).toBeNull();
    });

    it("leaves fields without a unit alone", () => {
        expect(ensureUnit(SCHEMA, "filename = sunset", 18)).toBeNull();
        expect(ensureUnit(SCHEMA, "width >= ", 9)).toBeNull();
    });
});

describe("typeCharacter", () => {
    it("steps over the unit when typing a space or comma", () => {
        const text = "width >= 12px";
        const caret = text.indexOf("px");

        expect(typeCharacter(SCHEMA, text, caret, " ")).toEqual({ text: "width >= 12px ", caret: text.length + 1 });
        expect(typeCharacter(SCHEMA, text, caret, ",")).toEqual({ text: "width >= 12px,", caret: text.length + 1 });
    });

    it("steps over a closing quote instead of doubling it", () => {
        const text = 'filename = ""';

        expect(typeCharacter(SCHEMA, text, 12, '"')).toEqual({ text, caret: 13 });
    });

    it("wraps the first letter of a text value in quotes", () => {
        const text = "filename = ";

        expect(typeCharacter(SCHEMA, text, text.length, "s")).toEqual({ text: 'filename = "s"', caret: text.length + 2 });
        expect(typeCharacter(SCHEMA, "filename in ", 12, "N")).toBeNull();
    });

    it("does not wrap inside existing quotes", () => {
        expect(typeCharacter(SCHEMA, 'filename = "s"', 13, "u")).toBeNull();
    });
});
