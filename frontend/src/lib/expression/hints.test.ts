import { describe, expect, it } from "vitest";
import { hintsFor } from "./hints";
import type { RuleSchema } from "./schema";

const OPERATORS = Object.fromEntries(
    ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "not_contains", "in"].map((name) => [
        name,
        { name, token: { eq: "=", neq: "!=", gt: ">", gte: ">=", lt: "<", lte: "<=" }[name] ?? name, label: name, doc: `${name} doc` },
    ]),
);

const schema: RuleSchema = {
    version: 1,
    capabilities: ["tokens", "completions", "docs", "snippets"],
    grammar: { keywords: [], operators: OPERATORS },
    detection: {
        path: "objects",
        label_field: "label",
        label_values: { source: "objects", values: ["dog", "cat"] },
        operators: ["present", "absent"],
        metrics: [
            {
                name: "confidence",
                label: "Confidence",
                description: "How sure the detector is.",
                kind: "number",
                operators: ["eq", "neq", "gt", "gte", "lt", "lte"],
                min: 0,
                max: 1,
                step: 0.01,
            },
        ],
    },
    groups: [
        {
            name: "Objects",
            label: "Objects",
            fields: [
                {
                    path: "objects",
                    group: "Objects",
                    label: "Detected object",
                    description: "An object found by the Object scanner.",
                    kind: "detection",
                    operators: ["present", "absent"],
                    computed: false,
                    values: { source: "objects", values: [] },
                },
            ],
        },
        {
            name: "Camera",
            label: "Camera",
            fields: [
                {
                    path: "exif.Make",
                    group: "Camera",
                    label: "Camera make",
                    description: "EXIF Make.",
                    kind: "text",
                    operators: ["eq", "neq", "contains", "in"],
                    computed: false,
                    values: { source: "distinct", values: [] },
                },
            ],
        },
        {
            name: "File",
            label: "File",
            fields: [
                {
                    path: "is_favorite",
                    group: "File",
                    label: "Favorite",
                    description: "Whether the photo is a favorite.",
                    kind: "bool",
                    operators: ["eq", "neq"],
                    computed: false,
                    values: { source: "none", values: [] },
                },
                {
                    path: "filename",
                    group: "File",
                    label: "Filename",
                    description: "The file name.",
                    kind: "text",
                    operators: ["eq", "neq", "contains", "in"],
                    computed: false,
                    values: { source: "none", values: [] },
                },
            ],
        },
    ],
};

const VALUES = { "exif.Make": ["Canon", "Nikon"] };

function hints(text: string, values: Record<string, string[]> = VALUES) {
    return hintsFor(schema, values, text, text.length);
}

describe("hintsFor", () => {
    it("offers the fields where a condition starts", () => {
        const state = hints("");

        expect(state?.title).toBe("Fields");
        expect(state?.hints.map((hint) => hint.insert)).toContain("filename ");
        expect(state?.hints.map((hint) => hint.insert)).toContain("objects has ");
    });

    it("offers the fields again after and / or / (", () => {
        for (const text of ["filename = \"a\" and ", "filename = \"a\" or ", "("]) {
            expect(hints(text)?.hints.map((hint) => hint.insert)).toContain("is_favorite ");
        }
    });

    it("filters the fields by the word being typed", () => {
        const state = hints("exif.Ma");

        expect(state?.start).toBe(0);
        expect(state?.hints.map((hint) => hint.label)).toEqual(["exif.Make"]);
    });

    it("offers only the operators the field allows", () => {
        expect(hints("exif.Make ")?.hints.map((hint) => hint.label)).toEqual(["=", "!=", "contains", "in"]);
        expect(hints("is_favorite ")?.hints.map((hint) => hint.label)).toEqual(["=", "!="]);
    });

    it("offers booleans, known values and a note for free values", () => {
        expect(hints("is_favorite = ")?.hints.map((hint) => hint.insert)).toEqual(["true", "false"]);
        expect(hints("exif.Make = ")?.hints.map((hint) => hint.insert)).toEqual(['"Canon"', '"Nikon"']);
        expect(hints("exif.Make = Can")?.hints.map((hint) => hint.insert)).toEqual(['"Canon"']);
        expect(hints("is_favorite = tr")?.hints.map((hint) => hint.insert)).toEqual(["true"]);
    });

    it("replaces the quote of a partially typed string", () => {
        const text = 'exif.Make = "Can';
        const state = hintsFor(schema, VALUES, text, text.length);

        expect(state?.start).toBe(text.length - 4);
        expect(state?.hints[0].insert).toBe('"Canon"');
    });

    it("explains the expected syntax when there is nothing to insert", () => {
        expect(hints("exif.Make in ")?.note).toContain("list");
        expect(hints("filename in ")?.note).toContain("list");
    });

    it("offers labels, metrics and metric operators for a detection", () => {
        expect(hints("objects ")?.hints.map((hint) => hint.insert)).toEqual(["has ", "has no "]);
        expect(hints("objects has ")?.hints.map((hint) => hint.insert)).toEqual(['"dog"', '"cat"']);
        expect(hints("objects has no ")?.hints.map((hint) => hint.insert)).toEqual(['"dog"', '"cat"']);
        expect(hints('objects has "dog" ')?.hints.map((hint) => hint.insert)).toEqual(["with "]);
        expect(hints('objects has "dog" with ')?.hints.map((hint) => hint.insert)).toEqual(["confidence "]);
        expect(hints('objects has "dog" with confidence ')?.hints.map((hint) => hint.label)).toEqual([
            "=",
            "!=",
            ">",
            ">=",
            "<",
            "<=",
        ]);
        expect(hints('objects has "dog" with confidence >= ')?.note).toContain("number");
    });

    it("offers the next metric after a comma", () => {
        expect(hints('objects has "dog" with confidence >= 0.8, ')?.hints.map((hint) => hint.insert)).toEqual([
            "confidence ",
        ]);
    });

    it("returns nothing in a spot it cannot help with", () => {
        expect(hints('objects has "dog" with confidence >= 0.8 ')).toBeNull();
        expect(hints("nope = ")).toBeNull();
    });
});
