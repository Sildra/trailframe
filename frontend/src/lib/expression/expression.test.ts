import { describe, expect, it } from "vitest";
import { parseExpression } from "./parser";
import { printDefinition } from "./printer";
import { validateDefinition, type RuleSchema } from "./schema";
import type { Definition } from "../rules";

const OPERATORS = Object.fromEntries(
    ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "not_contains", "in"].map((name) => [
        name,
        { name, token: name, label: name, doc: "" },
    ]),
);

const NUMBER_OPS = ["eq", "neq", "gt", "gte", "lt", "lte"] as const;

const schema: RuleSchema = {
    version: 1,
    capabilities: ["tokens", "completions", "docs", "snippets"],
    grammar: { keywords: [], operators: OPERATORS },
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
                operators: [...NUMBER_OPS],
                min: 0,
                max: 100,
                step: 1,
                unit: "%",
            },
            {
                name: "surface",
                label: "Surface",
                description: "",
                kind: "number",
                operators: [...NUMBER_OPS],
                min: 0,
                max: 100,
                step: 1,
                unit: "%",
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
                    description: "",
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
                    path: "exif.FNumber",
                    group: "Camera",
                    label: "Aperture",
                    description: "",
                    kind: "number",
                    operators: ["eq", "neq", "gt", "gte", "lt", "lte"],
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
                    operators: ["eq", "neq", "gt", "gte", "lt", "lte"],
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
                    path: "is_favorite",
                    group: "File",
                    label: "Favorite",
                    description: "",
                    kind: "bool",
                    operators: ["eq", "neq"],
                    computed: false,
                    values: { source: "none", values: [] },
                },
                {
                    path: "filename",
                    group: "File",
                    label: "Filename",
                    description: "",
                    kind: "text",
                    operators: ["eq", "neq", "contains", "in"],
                    computed: false,
                    values: { source: "none", values: [] },
                },
                {
                    path: "tags",
                    group: "File",
                    label: "Tags",
                    description: "",
                    kind: "list",
                    operators: ["contains", "not_contains"],
                    computed: false,
                    values: { source: "tags", values: [] },
                },
            ],
        },
        {
            name: "Place",
            label: "Place",
            fields: [
                {
                    path: "country",
                    group: "Place",
                    label: "Country",
                    description: "",
                    kind: "text",
                    operators: ["eq", "neq", "contains", "in"],
                    computed: false,
                    values: { source: "distinct", values: [] },
                },
            ],
        },
    ],
};

function definition(source: string, ruleSchema?: RuleSchema): Definition {
    const result = parseExpression(source, ruleSchema);

    expect(result.issues).toEqual([]);
    expect(result.definition).not.toBeNull();

    return result.definition as Definition;
}

describe("parseExpression", () => {
    it("parses a detection with metrics bound to the label", () => {
        const parsed = definition('objects has "dog" with confidence >= 0.8, surface >= 0.1');

        expect(parsed.conditions).toEqual([
            {
                type: "detection",
                label: "dog",
                op: "present",
                metrics: [
                    { name: "confidence", op: "gte", value: 0.8 },
                    { name: "surface", op: "gte", value: 0.1 },
                ],
            },
        ]);
    });

    it("parses an absent detection", () => {
        expect(definition('objects has no "cat"').conditions[0]).toMatchObject({
            type: "detection",
            label: "cat",
            op: "absent",
        });
    });

    it("parses booleans with is / is not", () => {
        expect(definition("is_favorite is true").conditions[0]).toMatchObject({ op: "eq", value: true });
        expect(definition("is_favorite is not false").conditions[0]).toMatchObject({ op: "neq", value: false });
    });

    it("parses lists", () => {
        expect(definition('country in ["Norway", "Sweden"]').conditions[0]).toMatchObject({
            op: "in",
            value: ["Norway", "Sweden"],
        });
    });

    it("gives and precedence over or", () => {
        const parsed = definition('filename contains "a" and country = "Norway" or is_favorite is true');

        expect(parsed.match).toBe("any");
        expect(parsed.conditions).toHaveLength(2);
        expect(parsed.conditions[0]).toMatchObject({ type: "group", match: "all" });
    });

    it("keeps explicit groups", () => {
        const parsed = definition('is_favorite is true or (filename contains "a" and country = "Norway")');

        expect(parsed.match).toBe("any");
        expect(parsed.conditions[1]).toMatchObject({ type: "group", match: "all" });
    });

    it("reports a readable issue for malformed input", () => {
        expect(parseExpression('objects has "dog" with').issues[0].message).toContain("metric name");
        expect(parseExpression("").issues[0].message).toContain("empty");
    });
});

describe("printDefinition", () => {
    it("round-trips a nested definition", () => {
        const source =
            'objects has "dog" with confidence >= 0.8 or (is_favorite is true and filename contains "sunset")';
        const parsed = definition(source);

        expect(parseExpression(printDefinition(parsed)).definition).toEqual(parsed);
    });

    it("quotes text values and prints dates bare", () => {
        expect(printDefinition(definition('filename contains "sun"'))).toBe('filename contains "sun"');
        expect(printDefinition(definition('country = "Norway"'))).toBe('country = "Norway"');
    });
});

describe("units", () => {
    it("requires the unit the schema declares", () => {
        expect(parseExpression('objects has "dog" with confidence >= 80', schema).issues[0].message).toContain("unit");
        expect(parseExpression("width >= 1200", schema).issues[0].message).toContain("unit");
        expect(parseExpression("exif.FNumber >= 2.8", schema).issues[0].message).toContain("unit");
    });

    it("parses suffix and prefix units into plain numbers", () => {
        expect(definition('objects has "dog" with confidence >= 80%', schema).conditions[0]).toMatchObject({
            metrics: [{ name: "confidence", op: "gte", value: 80 }],
        });
        expect(definition("width >= 1200px", schema).conditions[0]).toMatchObject({ value: 1200 });
        expect(definition("exif.FNumber >= f/2.8", schema).conditions[0]).toMatchObject({ value: 2.8 });
    });

    it("rejects a unit the schema does not expect", () => {
        expect(parseExpression("filename = 35mm", schema).issues[0].message).toContain("Unexpected");
        expect(parseExpression("width >= 1200mm", schema).issues[0].message).toContain("px");
    });

    it("writes the units back", () => {
        const source = 'objects has "dog" with confidence >= 80% and width >= 1200px and exif.FNumber >= f/2.8';

        expect(printDefinition(definition(source, schema), schema)).toBe(source);
        expect(printDefinition(definition('objects has "dog" with confidence >= 80'), schema)).toContain("80%");
    });
});

describe("validateDefinition", () => {
    it("accepts a definition the schema supports", () => {
        expect(validateDefinition(schema, definition('objects has "dog" with confidence >= 80% and is_favorite is true', schema))).toEqual([]);
    });

    it("rejects metric values outside the served range", () => {
        const outOfRange = definition('objects has "dog" with confidence >= 120%', schema);

        expect(validateDefinition(schema, outOfRange)[0].message).toContain("between");
    });

    it("rejects unknown fields and unsupported operators", () => {
        const unknown = definition('nope = "x"');
        const unsupported = definition('filename > "x"');

        expect(validateDefinition(schema, unknown)[0].message).toContain("Unknown field");
        expect(validateDefinition(schema, unsupported)[0].message).toContain("cannot be used");
    });

    it("rejects an empty definition", () => {
        expect(validateDefinition(schema, { version: 1, match: "all", conditions: [] })[0].message).toContain("at least one");
    });
});
