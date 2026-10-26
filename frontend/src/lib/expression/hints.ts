/** Contextual hints for the rule expression language: fields, operators, values. */

import type { ScalarOperator } from "../rules";
import { fieldFor, type RuleSchema, type SchemaField, type SchemaMetric } from "./schema";
import { tokenize, type Token } from "./tokens";

export type HintKind = "field" | "operator" | "value" | "label" | "metric" | "keyword";

export interface Hint {
    /** Text inserted at the caret, replacing the word being typed. */
    insert: string;
    /** What the chip shows. */
    label: string;
    /** The tooltip. */
    detail: string;
    kind: HintKind;
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

const MAX_HINTS = 10;

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

function quoted(value: string): string {
    return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

function word(token: Token | undefined): string {
    return token?.kind === "word" ? token.text.toLowerCase() : "";
}

/** The tokens of the condition the caret sits in. */
function lastSegment(tokens: Token[]): Token[] {
    let start = 0;

    tokens.forEach((token, index) => {
        const isJoiner = token.kind === "word" && ["and", "or"].includes(token.text.toLowerCase());
        const isGroup = token.kind === "punct" && token.text === "(";

        if (isJoiner || isGroup) {
            start = index + 1;
        }
    });

    return tokens.slice(start);
}

function filterHints(hints: Hint[], partial: string): Hint[] {
    const needle = partial.toLowerCase();

    if (!needle) {
        return hints.slice(0, MAX_HINTS);
    }

    return hints.filter((hint) => hint.label.toLowerCase().includes(needle)).slice(0, MAX_HINTS);
}

function fieldHints(schema: RuleSchema): Hint[] {
    return schema.groups.flatMap((group) =>
        group.fields.map((field) => ({
            insert: field.kind === "detection" ? `${field.path} has ` : `${field.path} `,
            label: field.kind === "detection" ? `${field.path} has` : field.path,
            detail: `${field.label} — ${field.description}`,
            kind: "field" as const,
        })),
    );
}

function operatorHints(schema: RuleSchema, field: SchemaField): Hint[] {
    return (field.operators as ScalarOperator[]).map((op) => {
        const spec = schema.grammar.operators[op];

        return {
            insert: `${spec?.token ?? op} `,
            label: spec?.token ?? op,
            detail: spec ? `${spec.label} — ${spec.doc}` : field.label,
            kind: "operator" as const,
        };
    });
}

function valueHints(values: Record<string, string[]>, field: SchemaField): Hint[] {
    const known = field.values.source === "static" ? field.values.values : (values[field.path] ?? []);

    return known.map((value) => ({
        insert: quoted(value),
        label: value,
        detail: field.label,
        kind: "value" as const,
    }));
}

function metricHints(metric: SchemaMetric): Hint {
    return {
        insert: `${metric.name} `,
        label: metric.name,
        detail: metric.description,
        kind: "metric",
    };
}

function labelHints(schema: RuleSchema): Hint[] {
    return schema.detection.label_values.values.map((label) => ({
        insert: quoted(label),
        label,
        detail: "A detected object label",
        kind: "label" as const,
    }));
}

function scalarHints(
    schema: RuleSchema,
    values: Record<string, string[]>,
    field: SchemaField,
    rest: Token[],
): HintState | null {
    if (rest.length === 0) {
        return { start: 0, end: 0, title: `Operators for ${field.path}`, hints: operatorHints(schema, field) };
    }

    const op = OPERATOR_NAMES[word(rest[0])] ?? OPERATOR_NAMES[rest[0]?.text ?? ""];

    if (rest.length === 1) {
        if (op === "in") {
            return {
                start: 0,
                end: 0,
                title: `Values for ${field.path}`,
                hints: [],
                note: 'A list, e.g. ["Norway", "Sweden"]',
            };
        }

        if (field.kind === "bool") {
            return {
                start: 0,
                end: 0,
                title: `Values for ${field.path}`,
                hints: [
                    { insert: "true", label: "true", detail: "The value is true", kind: "value" },
                    { insert: "false", label: "false", detail: "The value is false", kind: "value" },
                ],
            };
        }

        if (field.kind === "number") {
            return {
                start: 0,
                end: 0,
                title: `Values for ${field.path}`,
                hints: [],
                note: `A number${field.unit ? ` in ${field.unit}` : ""}`,
            };
        }

        if (field.kind === "date") {
            return {
                start: 0,
                end: 0,
                title: `Values for ${field.path}`,
                hints: [],
                note: "A date as YYYY-MM-DD",
            };
        }

        return { start: 0, end: 0, title: `Values for ${field.path}`, hints: valueHints(values, field) };
    }

    if (rest.length === 2 && word(rest[0]) === "is" && word(rest[1]) === "not") {
        return { start: 0, end: 0, title: `Values for ${field.path}`, hints: valueHints(values, field) };
    }

    return null;
}

function detectionHints(schema: RuleSchema, rest: Token[]): HintState | null {
    const withIndex = rest.findIndex((token) => word(token) === "with");

    if (withIndex >= 0) {
        const metrics = rest.slice(withIndex + 1);
        const step = metrics.length % 4;

        if (step === 0) {
            return {
                start: 0,
                end: 0,
                title: "Metrics",
                hints: schema.detection.metrics.map(metricHints),
            };
        }

        if (step === 1) {
            const name = word(metrics[metrics.length - 1]);
            const metric = schema.detection.metrics.find((item) => item.name === name);

            return {
                start: 0,
                end: 0,
                title: name ? `Operators for ${name}` : "Operators",
                hints: (metric?.operators ?? []).map((op) => {
                    const spec = schema.grammar.operators[op];

                    return {
                        insert: `${spec?.token ?? op} `,
                        label: spec?.token ?? op,
                        detail: spec?.doc ?? op,
                        kind: "operator" as const,
                    };
                }),
            };
        }

        if (step === 2) {
            return {
                start: 0,
                end: 0,
                title: "Metric value",
                hints: [],
                note: "A number, e.g. 0.8",
            };
        }

        return null;
    }

    if (rest.length === 0) {
        return {
            start: 0,
            end: 0,
            title: "Detection",
            hints: [
                { insert: "has ", label: "has", detail: "The photo contains an object", kind: "keyword" },
                { insert: "has no ", label: "has no", detail: "The photo contains no such object", kind: "keyword" },
            ],
        };
    }

    const no = word(rest[1]) === "no";
    const labelIndex = no ? 2 : 1;

    if (rest.length <= labelIndex) {
        return { start: 0, end: 0, title: "Object labels", hints: labelHints(schema) };
    }

    return {
        start: 0,
        end: 0,
        title: "Detection",
        hints: [{ insert: "with ", label: "with", detail: "Narrow the detection by its metrics", kind: "keyword" }],
    };
}

/**
 * The hints for the caret position: the fields where a condition starts, the
 * operators after a field, the values after an operator, labels and metrics.
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

    const segment = lastSegment(tokens);
    const first = segment[0];
    let state: HintState | null = null;

    if (segment.length === 0) {
        state = { start, end, title: "Fields", hints: fieldHints(schema) };
    } else if (first.kind === "word" && first.text.toLowerCase() === "objects") {
        state = detectionHints(schema, segment.slice(1));
    } else if (first.kind === "word") {
        const field = fieldFor(schema, first.text);

        state = field ? scalarHints(schema, values, field, segment.slice(1)) : null;
    }

    if (state === null) {
        return null;
    }

    const hints = filterHints(state.hints, partial);

    if (hints.length === 0 && !state.note) {
        return null;
    }

    return { ...state, start, end, hints };
}