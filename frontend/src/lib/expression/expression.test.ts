import { describe, expect, it } from "vitest";
import { parseExpression } from "./parser";
import { printDefinition } from "./printer";
import { validateDefinition, type RuleSchema } from "./schema";
import type { Definition, ElementCondition, Quantifier } from "../rules";

const OPERATORS = Object.fromEntries(
    ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "not_contains", "in"].map((name) => [
        name,
        {
            name,
            token: { eq: "=", neq: "!=", gt: ">", gte: ">=", lt: "<", lte: "<=" }[name] ?? name,
            label: name,
            doc: "",
        },
    ]),
);

const NUMBER_OPS = ["eq", "neq", "gt", "gte", "lt", "lte"] as const;
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
            description: "",
            quantifiers: ALL_QUANTIFIERS,
            elements: [
                {
                    key: "label",
                    label: "Label",
                    description: "",
                    kind: "text",
                    operators: ["eq", "neq", "contains", "in"],
                    values: { source: "objects", values: [] },
                },
                {
                    key: "confidence",
                    label: "Confidence",
                    description: "",
                    kind: "number",
                    operators: [...NUMBER_OPS],
                    values: { source: "none", values: [] },
                    min: 0,
                    max: 1,
                    step: 0.01,
                    unit: "%",
                },
                {
                    key: "surface",
                    label: "Surface",
                    description: "",
                    kind: "number",
                    operators: [...NUMBER_OPS],
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
            description: "",
            quantifiers: ALL_QUANTIFIERS,
            elements: [
                {
                    key: "step",
                    label: "Step",
                    description: "",
                    kind: "text",
                    operators: ["eq", "neq", "in"],
                    values: { source: "static", values: ["tilt", "crop", "rescale"] },
                },
                {
                    key: "meta.applied",
                    label: "Tilt applied",
                    description: "",
                    kind: "bool",
                    operators: ["eq", "neq"],
                    values: { source: "none", values: [] },
                },
                {
                    key: "meta.crop_mode",
                    label: "Crop mode",
                    description: "",
                    kind: "text",
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
                    path: "exif.FNumber",
                    group: "Camera",
                    label: "Aperture",
                    description: "",
                    kind: "number",
                    operators: [...NUMBER_OPS],
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
                    operators: [...NUMBER_OPS],
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

function definition(source: string): Definition {
    const result = parseExpression(source);

    expect(result.issues).toEqual([]);
    expect(result.definition).not.toBeNull();

    return result.definition as Definition;
}

function element(key: string, op: string, value: ElementCondition["value"]): ElementCondition {
    return { type: "element", key, op: op as ElementCondition["op"], value };
}

describe("parseExpression", () => {
    it("parses a quantified collection filter", () => {
        const parsed = definition('objects [label = "dog" and confidence >= 80%] has any');

        expect(parsed.version).toBe(2);
        expect(parsed.conditions).toEqual([
            {
                type: "collection",
                path: "objects",
                quantifier: "any",
                condition: {
                    type: "group",
                    match: "all",
                    conditions: [element("label", "eq", "dog"), element("confidence", "gte", 0.8)],
                },
            },
        ]);
    });

    it("parses every quantifier", () => {
        for (const quantifier of ALL_QUANTIFIERS) {
            expect(definition(`objects [label = "dog"] has ${quantifier}`).conditions[0]).toMatchObject({
                type: "collection",
                quantifier,
            });
        }
    });

    it("parses nested element groups", () => {
        const parsed = definition('objects [(label = "dog" or label = "cat") and confidence >= 50%] has any');
        const collection = parsed.conditions[0];

        expect(collection).toMatchObject({
            type: "collection",
            condition: {
                type: "group",
                match: "all",
                conditions: [
                    { type: "group", match: "any", conditions: [element("label", "eq", "dog"), element("label", "eq", "cat")] },
                    element("confidence", "gte", 0.5),
                ],
            },
        });
    });

    it("parses dotted element keys", () => {
        const parsed = definition('processing [step = "tilt" and meta.applied is true] has any');

        expect(parsed.conditions[0]).toMatchObject({
            type: "collection",
            path: "processing",
            condition: {
                type: "group",
                match: "all",
                conditions: [element("step", "eq", "tilt"), element("meta.applied", "eq", true)],
            },
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

    it("pushes not down to the leaves", () => {
        expect(definition("not is_favorite is true").conditions).toEqual([
            { type: "scalar", path: "is_favorite", op: "neq", value: true },
        ]);

        const parsed = definition('not (is_favorite is true or filename contains "a")');

        expect(parsed.match).toBe("all");
        expect(parsed.conditions).toEqual([
            { type: "scalar", path: "is_favorite", op: "neq", value: true },
            { type: "scalar", path: "filename", op: "not_contains", value: "a" },
        ]);
    });

    it("rejects not before a collection", () => {
        expect(parseExpression('not objects [label = "dog"] has any').issues[0].message).toContain("has none");
    });

    it("rejects a bare key without a comparison", () => {
        expect(parseExpression("meta.applied").issues[0].message).toContain("comparison operator");
        expect(parseExpression("objects [meta.applied] has any").issues[0].message).toContain("comparison operator");
    });

    it("reports a readable issue for malformed input", () => {
        expect(parseExpression('objects [label = "dog"]').issues[0].message).toContain("has");
        expect(parseExpression("").issues[0].message).toContain("empty");
    });
});

describe("printDefinition", () => {
    it("round-trips a nested definition", () => {
        const source =
            'objects [label = "dog" and confidence >= 80%] has any or (is_favorite is true and filename contains "sunset")';
        const parsed = definition(source);

        expect(printDefinition(parsed, schema)).toBe(source);
        expect(parseExpression(printDefinition(parsed, schema)).definition).toEqual(parsed);
    });

    it("round-trips nested element groups", () => {
        const source = 'objects [(label = "dog" or label = "cat") and confidence >= 50%] has any';
        const parsed = definition(source);

        expect(printDefinition(parsed, schema)).toBe(source);
    });

    it("quotes text values and prints dates bare", () => {
        expect(printDefinition(definition('filename contains "sun"'))).toBe('filename contains "sun"');
        expect(printDefinition(definition('country = "Norway"'))).toBe('country = "Norway"');
    });

    it("writes percentages back on the 0-100 scale", () => {
        expect(printDefinition(definition("objects [confidence >= 0.8] has any"), schema)).toBe(
            "objects [confidence >= 80%] has any",
        );
    });

    it("writes the units declared by the schema", () => {
        const source = "width >= 1200px and exif.FNumber >= f/2.8";
        const parsed = definition(source);

        expect(printDefinition(parsed, schema)).toBe(source);
        expect(printDefinition(parsed)).toBe("width >= 1200 and exif.FNumber >= 2.8");
    });
});

describe("units", () => {
    it("treats units as optional sugar", () => {
        const parsed = definition("objects [confidence >= 80] has any");

        expect(parsed.conditions[0]).toMatchObject({
            condition: element("confidence", "gte", 80),
        });
    });

    it("parses suffix and prefix units into plain numbers", () => {
        expect(definition("objects [confidence >= 80%] has any").conditions[0]).toMatchObject({
            condition: element("confidence", "gte", 0.8),
        });
        expect(definition("width >= 1200px").conditions[0]).toMatchObject({ value: 1200 });
        expect(definition("width >= 1200").conditions[0]).toMatchObject({ value: 1200 });
        expect(definition("exif.FNumber >= f/2.8").conditions[0]).toMatchObject({ value: 2.8 });
    });

    it("ignores units other than percent", () => {
        expect(definition("width >= 1200mm").conditions[0]).toMatchObject({ value: 1200 });
    });
});

describe("validateDefinition", () => {
    it("accepts a definition the schema supports", () => {
        expect(
            validateDefinition(
                schema,
                definition('objects [label = "dog" and confidence >= 80%] has any and is_favorite is true'),
            ),
        ).toEqual([]);
    });

    it("accepts element keys the schema declares", () => {
        expect(
            validateDefinition(schema, definition('processing [step = "tilt" and meta.applied is true] has any')),
        ).toEqual([]);
    });

    it("rejects values outside the served range", () => {
        const outOfRange = definition("objects [confidence >= 120%] has any");

        expect(validateDefinition(schema, outOfRange)[0].message).toContain("between");
    });

    it("rejects a percentage written without its sign", () => {
        const bare = definition("objects [confidence >= 80] has any");

        expect(validateDefinition(schema, bare)[0].message).toContain("between 0 and 1");
    });

    it("rejects unknown collections and keys", () => {
        expect(validateDefinition(schema, definition('things [label = "x"] has any'))[0].message).toContain(
            "Unknown collection",
        );
        expect(validateDefinition(schema, definition('objects [nope = "x"] has any'))[0].message).toContain(
            "Unknown objects key",
        );
    });

    it("rejects elements outside a collection and collections inside one", () => {
        const strayElement: Definition = {
            version: 2,
            match: "all",
            conditions: [element("label", "eq", "dog")],
        };
        const nestedCollection: Definition = {
            version: 2,
            match: "all",
            conditions: [
                {
                    type: "collection",
                    path: "objects",
                    quantifier: "any",
                    condition: {
                        type: "collection",
                        path: "processing",
                        quantifier: "any",
                        condition: element("step", "eq", "tilt"),
                    },
                },
            ],
        };

        expect(validateDefinition(schema, strayElement)[0].message).toContain("inside a collection");
        expect(validateDefinition(schema, nestedCollection)[0].message).toContain("cannot be nested");
    });

    it("rejects unknown fields and unsupported operators", () => {
        const unknown = definition('nope = "x"');
        const unsupported = definition('filename > "x"');

        expect(validateDefinition(schema, unknown)[0].message).toContain("Unknown field");
        expect(validateDefinition(schema, unsupported)[0].message).toContain("cannot be used");
    });

    it("rejects an empty definition", () => {
        expect(validateDefinition(schema, { version: 2, match: "all", conditions: [] })[0].message).toContain(
            "at least one",
        );
    });
});
