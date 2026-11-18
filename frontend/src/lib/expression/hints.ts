/** Contextual hints for the rule expression language: fields, keys, operators, values. */

import type { ScalarOperator } from "../rules";
import { currentSegment, openCollection } from "./context";
import {
    collectionFor,
    elementFor,
    fieldFor,
    type FieldKind,
    type RuleSchema,
    type SchemaCollection,
    type SchemaElement,
    type SchemaField,
    type ValueSource,
} from "./schema";
import { tokenize, type Token } from "./tokens";

export type HintKind = "field" | "operator" | "value" | "element" | "quantifier" | "keyword";

export interface Hint {
    /** Text inserted at the caret, replacing the word being typed. */
    insert: string;
    /** What the chip shows. */
    label: string;
    /** The tooltip. */
    detail: string;
    kind: HintKind;
    /** Where to put the caret inside `insert`; defaults to its end. */
    caret?: number;
}

export interface HintState {
    /** Start of the source range a hint replaces. */
    start: number;
    /** End of that range: the caret. */
    end: number;
    /** What the hints are for, shown before the chips. */
    title: string;
    hints: Hint[];
    /** Advice when there is nothing to insert, e.g. a free-form number. */
    note?: string;
}

const MAX_HINTS = 12;

/** Operators as written in an expression, mapped to their schema names. */
const OPERATOR_NAMES: Record<string, ScalarOperator> = {
    "=": "eq",
    is: "eq",
    "!=": "neq",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
    contains: "contains",
    "!contains": "not_contains",
    in: "in",
};

/** One value slot: a scalar field or one key of a collection element. */
interface ValueSpec {
    /** Key into the served value dictionaries. */
    key: string;
    /** The path or `collection.key` shown in the hint title. */
    label: string;
    kind: FieldKind;
    values: ValueSource;
    unit?: string;
}

function quoted(value: string): string {
    return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

function word(token: Token | undefined): string {
    return token?.kind === "word" ? token.text.toLowerCase() : "";
}

function filterHints(hints: Hint[], partial: string): Hint[] {
    const needle = partial.toLowerCase();

    if (!needle) {
        return hints.slice(0, MAX_HINTS);
    }

    return hints.filter((hint) => hint.label.toLowerCase().includes(needle)).slice(0, MAX_HINTS);
}

function specOfField(field: SchemaField): ValueSpec {
    return { key: field.path, label: field.path, kind: field.kind, values: field.values, unit: field.unit };
}

function specOfElement(element: SchemaElement, collection: SchemaCollection): ValueSpec {
    const key = element.values.source === "objects" ? "objects" : element.key;

    return {
        key,
        label: `${collection.path}.${element.key}`,
        kind: element.kind,
        values: element.values,
        unit: element.unit,
    };
}

function knownValues(values: Record<string, string[]>, spec: ValueSpec): string[] {
    if (spec.values.source === "static") {
        return spec.values.values;
    }

    return values[spec.key] ?? [];
}

function fieldHints(schema: RuleSchema): Hint[] {
    const fields = schema.groups.flatMap((group) =>
        group.fields.map((field): Hint => {
            const detail = `${field.label} — ${field.description}`;

            // Text-like values get their quotes and comparison filled in, with
            // the caret inside the quotes so typing lands in the right place.
            if (field.kind === "text" || field.kind === "enum") {
                const insert = `${field.path} = ""`;

                return { insert, label: field.path, detail, kind: "field", caret: insert.length - 1 };
            }

            if (field.kind === "list") {
                const insert = `${field.path} contains ""`;

                return { insert, label: field.path, detail, kind: "field", caret: insert.length - 1 };
            }

            return { insert: `${field.path} `, label: field.path, detail, kind: "field" };
        }),
    );

    const collections = schema.collections.map((collection): Hint => {
        const insert = `${collection.path} [] has any`;

        return {
            insert,
            label: collection.path,
            detail: `${collection.label} — ${collection.description}`,
            kind: "field",
            caret: collection.path.length + 2,
        };
    });

    return [...fields, ...collections];
}

function operatorHints(schema: RuleSchema, operators: ScalarOperator[], fallback: string): Hint[] {
    return operators.map((op) => {
        const spec = schema.grammar.operators[op];

        return {
            insert: `${spec?.token ?? op} `,
            label: spec?.token ?? op,
            detail: spec ? `${spec.label} — ${spec.doc}` : fallback,
            kind: "operator" as const,
        };
    });
}

function valueHints(values: Record<string, string[]>, spec: ValueSpec): Hint[] {
    return knownValues(values, spec).map((value) => ({
        insert: quoted(value),
        label: value,
        detail: spec.label,
        kind: "value" as const,
    }));
}

function elementHint(element: SchemaElement): Hint {
    const detail = `${element.label} — ${element.description}`;

    if (element.kind === "text" || element.kind === "enum") {
        const insert = `${element.key} = ""`;

        return { insert, label: element.key, detail, kind: "element", caret: insert.length - 1 };
    }

    if (element.kind === "list") {
        const insert = `${element.key} contains ""`;

        return { insert, label: element.key, detail, kind: "element", caret: insert.length - 1 };
    }

    if (element.kind === "bool") {
        return { insert: `${element.key} is `, label: element.key, detail, kind: "element" };
    }

    return { insert: `${element.key} `, label: element.key, detail, kind: "element" };
}

/** The advice shown where a free number is allowed. */
function numberNote(unit: string | undefined): string {
    if (unit === "%") {
        return "A percentage from 0 to 100, e.g. 80%";
    }

    if (unit) {
        return `A number in ${unit}`;
    }

    return "A number";
}

function quantifierHints(schema: RuleSchema, withHas: boolean): Hint[] {
    return schema.quantifiers.map((quantifier) => ({
        insert: withHas ? `has ${quantifier.name}` : quantifier.name,
        label: withHas ? `has ${quantifier.name}` : quantifier.name,
        detail: quantifier.doc,
        kind: "quantifier" as const,
    }));
}

/** Operators, then the operand, for one field or element key. */
function predicateHints(
    schema: RuleSchema,
    values: Record<string, string[]>,
    spec: ValueSpec,
    operators: ScalarOperator[],
    rest: Token[],
): HintState | null {
    if (rest.length === 0) {
        return { start: 0, end: 0, title: `Operators for ${spec.label}`, hints: operatorHints(schema, operators, spec.label) };
    }

    const op = OPERATOR_NAMES[word(rest[0])] ?? OPERATOR_NAMES[rest[0]?.text ?? ""];

    if (rest.length === 1) {
        if (op === "in") {
            return {
                start: 0,
                end: 0,
                title: `Values for ${spec.label}`,
                hints: [],
                note: 'A list, e.g. ["Norway", "Sweden"]',
            };
        }

        if (spec.kind === "bool") {
            return {
                start: 0,
                end: 0,
                title: `Values for ${spec.label}`,
                hints: [
                    { insert: "true", label: "true", detail: "The value is true", kind: "value" },
                    { insert: "false", label: "false", detail: "The value is false", kind: "value" },
                ],
            };
        }

        if (spec.kind === "number") {
            return { start: 0, end: 0, title: `Values for ${spec.label}`, hints: [], note: numberNote(spec.unit) };
        }

        if (spec.kind === "date") {
            return {
                start: 0,
                end: 0,
                title: `Values for ${spec.label}`,
                hints: [],
                note: "A date as YYYY-MM-DD",
            };
        }

        return { start: 0, end: 0, title: `Values for ${spec.label}`, hints: valueHints(values, spec) };
    }

    if (rest.length === 2 && word(rest[0]) === "is" && word(rest[1]) === "not") {
        return { start: 0, end: 0, title: `Values for ${spec.label}`, hints: valueHints(values, spec) };
    }

    return null;
}

/** What can follow a complete element condition: a joiner, or closing the filter. */
function joinerHints(): Hint[] {
    return [
        { insert: "and ", label: "and", detail: "Both must match", kind: "keyword" },
        { insert: "or ", label: "or", detail: "Either may match", kind: "keyword" },
        { insert: "] has any", label: "] has any", detail: "Close the filter", kind: "quantifier" },
    ];
}

function elementHints(
    schema: RuleSchema,
    values: Record<string, string[]>,
    collection: SchemaCollection,
    segment: Token[],
): HintState | null {
    if (segment.length === 0) {
        return {
            start: 0,
            end: 0,
            title: `${collection.label} keys`,
            hints: collection.elements.map((element) => elementHint(element)),
        };
    }

    const first = segment[0];

    if (first.kind !== "word") {
        return null;
    }

    const element = elementFor(collection, first.text);

    if (!element) {
        return null;
    }

    if (segment.length === 1) {
        return {
            start: 0,
            end: 0,
            title: `Operators for ${element.key}`,
            hints: operatorHints(schema, element.operators, element.label),
        };
    }

    const state = predicateHints(
        schema,
        values,
        specOfElement(element, collection),
        element.operators,
        segment.slice(1),
    );

    if (state) {
        return state;
    }

    if (segment.length >= 3) {
        return { start: 0, end: 0, title: "Continue the filter", hints: joinerHints() };
    }

    return null;
}

/** The steps after a collection path: its filter, then `has <quantifier>`. */
function collectionHints(schema: RuleSchema, rest: Token[]): HintState | null {
    if (rest.length === 0) {
        return {
            start: 0,
            end: 0,
            title: "Filter",
            hints: [{ insert: "[", label: "[", detail: "Open the element filter", kind: "keyword" }],
        };
    }

    if (!(rest[0].kind === "punct" && rest[0].text === "[")) {
        return null;
    }

    const close = rest.findIndex((token) => token.kind === "punct" && token.text === "]");

    if (close < 0) {
        return null;
    }

    const after = rest.slice(close + 1);

    if (after.length === 0) {
        return { start: 0, end: 0, title: "Quantifier", hints: quantifierHints(schema, true) };
    }

    if (after.length === 1 && word(after[0]) === "has") {
        return { start: 0, end: 0, title: "Quantifier", hints: quantifierHints(schema, false) };
    }

    return null;
}

function rootHints(schema: RuleSchema, values: Record<string, string[]>, segment: Token[]): HintState | null {
    if (segment.length === 0) {
        return { start: 0, end: 0, title: "Fields", hints: fieldHints(schema) };
    }

    const first = segment[0];

    if (first.kind !== "word") {
        return null;
    }

    const collection = collectionFor(schema, first.text);

    if (collection) {
        return collectionHints(schema, segment.slice(1));
    }

    const field = fieldFor(schema, first.text);

    if (!field) {
        return null;
    }

    return predicateHints(schema, values, specOfField(field), field.operators, segment.slice(1));
}

/**
 * True when `partial` is a step keyword that the grammar already moved past, so
 * the hints belong to the step after it even though no space was typed yet:
 * `objects [` (nothing), `objects […] has`, `exif.Make is`, `… and`.
 */
function completesStep(schema: RuleSchema, tokens: Token[], partial: string): boolean {
    const bracket = openCollection(schema, tokens);
    const segment = currentSegment(bracket ? tokens.slice(bracket.open + 1) : tokens);

    if (segment.length === 0) {
        return false;
    }

    if (partial === "and" || partial === "or") {
        return segment.length >= 3;
    }

    if (partial === "has") {
        const last = segment[segment.length - 1];

        return last.kind === "punct" && last.text === "]";
    }

    if (partial === "is" || partial === "contains" || partial === "in") {
        return segment.length === 1;
    }

    if (partial === "not") {
        return segment.length === 2 && word(segment[1]) === "is";
    }

    return false;
}

/**
 * The hints for the caret position: fields where a condition starts, element
 * keys inside a filter, the operators after a field or key, and the values.
 */
export function hintsFor(
    schema: RuleSchema,
    values: Record<string, string[]>,
    text: string,
    caret: number,
): HintState | null {
    const end = Math.max(0, Math.min(caret, text.length));
    const tokens = tokenize(text.slice(0, end)).tokens.filter((token) => token.kind !== "eof");
    const last = tokens[tokens.length - 1];
    let partial = "";
    let start = end;

    if (last && last.end === end && (last.kind === "word" || last.kind === "string" || last.kind === "number" || last.kind === "date")) {
        partial = last.kind === "string" ? last.text : last.raw;
        start = last.start;
        tokens.pop();
    }

    // The step keyword is already typed: hints belong after it, and a hint is
    // appended at the caret instead of replacing the keyword.
    if (partial && completesStep(schema, tokens, partial.toLowerCase())) {
        tokens.push({ kind: "word", text: partial, raw: partial, start, end });
        partial = "";
        start = end;
    }

    const bracket = openCollection(schema, tokens);
    const segment = currentSegment(bracket ? tokens.slice(bracket.open + 1) : tokens);
    const state = bracket
        ? elementHints(schema, values, bracket.collection, segment)
        : rootHints(schema, values, segment);

    if (state === null) {
        return null;
    }

    const hints = filterHints(state.hints, partial);

    if (hints.length === 0 && !state.note) {
        return null;
    }

    return { ...state, start, end, hints };
}
