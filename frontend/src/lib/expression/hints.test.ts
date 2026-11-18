import { describe, expect, it } from "vitest";
import { hintsFor } from "./hints";
import type { RuleSchema } from "./schema";
import type { Quantifier } from "../rules";

const OPERATORS = Object.fromEntries(
    ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "not_contains", "in"].map((name) => [
        name,
        {
            name,
            token: { eq: "=", neq: "!=", gt: ">", gte: ">=", lt: "<", lte: "<=" }[name] ?? name,
            label: name,
            doc: `${name} doc`,
        },
    ]),
);

const ALL_QUANTIFIERS: Quantifier[] = ["any", "none", "one", "all"];

const schema: RuleSchema = {
    version: 2,
    capabilities: ["tokens", "completions", "docs", "snippets"],
    grammar: { keywords: [], operators: OPERATORS },
    quantifiers: ALL_QUANTIFIERS.map((name) => ({ name, label: name, doc: `${name} doc` })),
    collections: [
        {
            path: "objects",
            group: "Objects",
            label: "Detected objects",
            description: "Objects found by the Object scanner.",
            quantifiers: ALL_QUANTIFIERS,
            elements: [
                {
                    key: "label",
                    label: "Label",
                    description: "The detected label.",
                    kind: "text",
                    operators: ["eq", "neq", "contains", "in"],
                    values: { source: "objects", values: [] },
                },
                {
                    key: "confidence",
                    label: "Confidence",
                    description: "How sure the detector is.",
                    kind: "number",
                    operators: ["eq", "neq", "gt", "gte", "lt", "lte"],
                    values: { source: "none", values: [] },
                    min: 0,
                    max: 1,
                    step: 0.01,
                    unit: "%",
                },
            ],
        },
        {
            path: "processing",
            group: "Processing",
            label: "Processing steps",
            description: "The preprocessing steps of the photo.",
            quantifiers: ALL_QUANTIFIERS,
            elements: [
                {
                    key: "step",
                    label: "Step",
                    description: "The step name.",
                    kind: "text",
                    operators: ["eq", "neq", "in"],
                    values: { source: "static", values: ["tilt", "crop", "rescale"] },
                },
                {
                    key: "meta.applied",
                    label: "Tilt applied",
                    description: "Whether the tilt was applied.",
                    kind: "bool",
                    operators: ["eq", "neq"],
                    values: { source: "none", values: [] },
                },
            ],
        },
    ],
    groups: [
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
                {
                    path: "tags",
                    group: "File",
                    label: "Tags",
                    description: "The photo tags.",
                    kind: "list",
                    operators: ["contains", "not_contains"],
                    computed: false,
                    values: { source: "tags", values: [] },
                },
            ],
        },
    ],
};

const VALUES = { "exif.Make": ["Canon", "Nikon"], objects: ["dog", "cat"] };

function hints(text: string, values: Record<string, string[]> = VALUES) {
    return hintsFor(schema, values, text, text.length);
}

function inserts(text: string, values?: Record<string, string[]>) {
    return hints(text, values)?.hints.map((hint) => hint.insert);
}

describe("hintsFor", () => {
    it("offers the fields and collections where a condition starts", () => {
        const state = hints("");

        expect(state?.title).toBe("Fields");
        expect(state?.hints.map((hint) => hint.insert)).toContain('filename = ""');
        expect(state?.hints.map((hint) => hint.insert)).toContain("is_favorite ");
        expect(state?.hints.map((hint) => hint.insert)).toContain("objects [] has any");
        expect(state?.hints.map((hint) => hint.insert)).toContain("processing [] has any");
    });

    it("fills in the quotes of a text field and puts the caret inside them", () => {
        const hint = hints("")?.hints.find((item) => item.label === "exif.Make");

        expect(hint?.insert).toBe('exif.Make = ""');
        expect(hint?.caret).toBe(hint ? hint.insert.length - 1 : -1);

        const tags = hints("")?.hints.find((item) => item.label === "tags");

        expect(tags?.insert).toBe('tags contains ""');

        const favorite = hints("")?.hints.find((item) => item.label === "is_favorite");

        expect(favorite?.insert).toBe("is_favorite ");
    });

    it("puts the caret inside a collection filter", () => {
        const hint = hints("")?.hints.find((item) => item.label === "objects");

        expect(hint?.insert).toBe("objects [] has any");
        expect(hint?.caret).toBe("objects [".length);
    });

    it("offers the fields again after and / or / (", () => {
        for (const text of ['filename = "a" and ', 'filename = "a" or ', "("]) {
            expect(inserts(text)).toContain("is_favorite ");
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
        expect(inserts("is_favorite = ")).toEqual(["true", "false"]);
        expect(inserts("exif.Make = ")).toEqual(['"Canon"', '"Nikon"']);
        expect(inserts("exif.Make = Can")).toEqual(['"Canon"']);
        expect(inserts("is_favorite = tr")).toEqual(["true"]);
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

    it("offers the element keys inside a filter", () => {
        const state = hints("objects [");

        expect(state?.title).toBe("Detected objects keys");
        expect(state?.hints.map((hint) => hint.insert)).toContain('label = ""');
        expect(state?.hints.map((hint) => hint.insert)).toContain("confidence ");
    });

    it("offers booleans for element keys", () => {
        expect(inserts("processing [")).toContain("meta.applied is ");
        expect(inserts("processing [meta.applied = ")).toEqual(["true", "false"]);
    });

    it("offers only the operators the element key allows", () => {
        expect(hints("objects [label ")?.hints.map((hint) => hint.label)).toEqual(["=", "!=", "contains", "in"]);
        expect(hints("objects [confidence ")?.hints.map((hint) => hint.label)).toEqual(["=", "!=", ">", ">=", "<", "<="]);
    });

    it("offers element values from the served dictionaries", () => {
        expect(inserts("objects [label = ")).toEqual(['"dog"', '"cat"']);
        expect(inserts('objects [label = "do')).toEqual(['"dog"']);
        expect(inserts("processing [step = ")).toEqual(['"tilt"', '"crop"', '"rescale"']);
    });

    it("notes the percent scale of a numeric element", () => {
        expect(hints("objects [confidence >= ")?.note).toContain("percentage");
    });

    it("offers joiners and closing the filter after a complete element condition", () => {
        expect(inserts('objects [label = "dog" ')).toEqual(["and ", "or ", "] has any"]);
    });

    it("offers the quantifiers after the filter closes", () => {
        expect(inserts('objects [label = "dog"] ')).toEqual(["has any", "has none", "has one", "has all"]);
        expect(inserts('objects [label = "dog"] has')).toEqual(["any", "none", "one", "all"]);
    });

    it("moves past a step keyword that has no trailing space yet", () => {
        expect(hints("objects [")?.title).toBe("Detected objects keys");
        expect(hints('objects [label = "dog" and')?.title).toBe("Detected objects keys");
        expect(hints('objects [label = "dog"] has')?.title).toBe("Quantifier");

        expect(inserts("exif.Make is")).toEqual(['"Canon"', '"Nikon"']);
        expect(inserts("exif.Make is not")).toEqual(['"Canon"', '"Nikon"']);
        expect(inserts("exif.Make contains")).toEqual(['"Canon"', '"Nikon"']);
        expect(hints("exif.Make in")?.note).toContain("list");

        expect(hints('exif.Make = "Canon" and')?.title).toBe("Fields");
        expect(hints('objects [label = "dog"] has any and')?.title).toBe("Fields");
    });

    it("keeps filtering while a key or operator is incomplete", () => {
        expect(inserts("objects [conf")).toEqual(["confidence "]);
        expect(inserts("exif.Make i")).toEqual(["contains ", "in "]);
    });

    it("returns nothing in a spot it cannot help with", () => {
        expect(hints("nope = ")).toBeNull();
        expect(hints("objects [nope ")).toBeNull();
    });
});
