/** Typing aids for the rule expression editor: units and quotes fill themselves in. */

import { fieldFor, type RuleSchema, type SchemaField, type SchemaMetric } from "./schema";
import { tokenize, type Token } from "./tokens";
import { isPrefixUnit } from "./units";

interface Slot {
    unit: string;
    /** Start of the number being typed. */
    valueStart: number;
    field?: SchemaField;
    metric?: SchemaMetric;
}

const NUMBER_BEING_TYPED = /^-?\d+(?:\.\d*)?$/;

const WORD_OPERATORS = new Set(["is", "not", "contains", "in"]);

function tokensBefore(text: string, caret: number): Token[] {
    return tokenize(text.slice(0, Math.max(0, Math.min(caret, text.length)))).tokens.filter(
        (token) => token.kind !== "eof",
    );
}

/** The tokens of the condition the caret sits in. */
function segmentOf(tokens: Token[]): Token[] {
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

function isOperator(token: Token | undefined): boolean {
    return !!token && (token.kind === "operator" || (token.kind === "word" && WORD_OPERATORS.has(token.text.toLowerCase())));
}

function lastNumber(tokens: Token[], from: number): number {
    for (let index = tokens.length - 1; index >= from; index -= 1) {
        if (tokens[index].kind === "number") {
            return index;
        }
    }

    return -1;
}

/**
 * The unit-bearing number slot at the caret, when the caret is right after a
 * field or detection-metric number: `exif.FocalLength >= 35` or
 * `objects has "dog" with confidence >= 80`.
 */
export function unitSlot(schema: RuleSchema, text: string, caret: number): Slot | null {
    const segment = segmentOf(tokensBefore(text, caret));
    const first = segment[0];

    if (!first || first.kind !== "word") {
        return null;
    }

    if (first.text.toLowerCase() === "objects") {
        const withIndex = segment.findIndex((token) => token.kind === "word" && token.text.toLowerCase() === "with");

        if (withIndex < 0) {
            return null;
        }

        let from = withIndex + 1;

        segment.forEach((token, index) => {
            if (index > withIndex && token.kind === "punct" && token.text === ",") {
                from = index + 1;
            }
        });

        const metricTokens = segment.slice(from);
        const name = metricTokens[0];

        if (!name || name.kind !== "word") {
            return null;
        }

        const index = lastNumber(metricTokens, 1);
        const metric = schema.detection.metrics.find((item) => item.name === name.text);

        if (index < 0 || !metric?.unit) {
            return null;
        }

        return { unit: metric.unit, valueStart: metricTokens[index].start, metric };
    }

    const field = fieldFor(schema, first.text);

    if (!field || field.kind !== "number" || !field.unit) {
        return null;
    }

    // A value inside a list is not a plain number slot.
    if (segment.some((token) => token.kind === "punct" && token.text === "[")) {
        return null;
    }

    const index = lastNumber(segment, 2);

    if (index < 2) {
        return null;
    }

    const before = segment[index - 1];
    const prefix = before.kind === "unit" && isPrefixUnit(before.text) && isOperator(segment[index - 2]);

    if (!prefix && !isOperator(before)) {
        return null;
    }

    return { unit: field.unit, valueStart: segment[index].start, field };
}

/**
 * Keep the unit attached to the number being typed. A suffix unit appears as
 * soon as a digit is typed (the caret stays before it, so more digits grow the
 * number); a prefix unit such as `f/` goes in front of the number.
 */
export function ensureUnit(schema: RuleSchema, text: string, caret: number): { text: string; caret: number } | null {
    const position = Math.max(0, Math.min(caret, text.length));
    const slot = unitSlot(schema, text, position);

    if (!slot) {
        return null;
    }

    const typed = text.slice(slot.valueStart, position);

    if (!NUMBER_BEING_TYPED.test(typed)) {
        return null;
    }

    if (isPrefixUnit(slot.unit)) {
        if (text.slice(0, slot.valueStart).endsWith(slot.unit)) {
            return null;
        }

        return {
            text: text.slice(0, slot.valueStart) + slot.unit + text.slice(slot.valueStart),
            caret: position + slot.unit.length,
        };
    }

    if (text.startsWith(slot.unit, position)) {
        return null;
    }

    return { text: text.slice(0, position) + slot.unit + text.slice(position), caret: position };
}

function textSlot(schema: RuleSchema, text: string, caret: number): SchemaField | null {
    const segment = segmentOf(tokensBefore(text, caret));

    if (segment.length !== 2) {
        return null;
    }

    const [first, second] = segment;
    const op = second.kind === "operator" || second.kind === "word" ? second.text.toLowerCase() : "";
    const field = first.kind === "word" ? fieldFor(schema, first.text) : undefined;

    if (!field || !["text", "enum", "list"].includes(field.kind) || op === "in") {
        return null;
    }

    if (!isOperator(second)) {
        return null;
    }

    return field;
}

/**
 * What a printable character should do at the caret, when it needs more than
 * the default insertion: step over the closing quote or the unit that is
 * already there, or wrap the first letter of a text value in quotes.
 */
export function typeCharacter(
    schema: RuleSchema,
    text: string,
    caret: number,
    character: string,
): { text: string; caret: number } | null {
    if (text[caret] === '"' && character === '"') {
        return { text, caret: caret + 1 };
    }

    if (character === " " || character === ",") {
        const slot = unitSlot(schema, text, caret);

        if (slot && !isPrefixUnit(slot.unit) && text.startsWith(slot.unit, caret)) {
            const after = caret + slot.unit.length;

            return {
                text: text.slice(0, after) + character + text.slice(after),
                caret: after + 1,
            };
        }
    }

    if (!/[A-Za-z0-9]/.test(character)) {
        return null;
    }

    if (text[caret] === '"' || text[caret - 1] === '"') {
        return null;
    }

    if (!textSlot(schema, text, caret)) {
        return null;
    }

    return { text: `${text.slice(0, caret)}"${character}"${text.slice(caret)}`, caret: caret + 2 };
}
