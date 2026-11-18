/** Typing aids for the rule expression editor: units and quotes fill themselves in. */

import { currentSegment, openCollection } from "./context";
import { elementFor, fieldFor, type RuleSchema, type SchemaElement, type SchemaField } from "./schema";
import { tokenize, type Token } from "./tokens";
import { isPrefixUnit } from "./units";

interface Slot {
    unit: string;
    /** Start of the number being typed. */
    valueStart: number;
    field?: SchemaField;
    element?: SchemaElement;
}

const NUMBER_BEING_TYPED = /^-?\d+(?:\.\d*)?$/;

const WORD_OPERATORS = new Set(["is", "not", "contains", "in"]);

const TEXT_KINDS = new Set(["text", "enum", "list"]);

function tokensBefore(text: string, caret: number): Token[] {
    return tokenize(text.slice(0, Math.max(0, Math.min(caret, text.length)))).tokens.filter(
        (token) => token.kind !== "eof",
    );
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

/** The tokens of the condition the caret sits in, with collection filters unwrapped. */
function localSegment(schema: RuleSchema, text: string, caret: number): { tokens: Token[]; segment: Token[] } {
    const tokens = tokensBefore(text, caret);
    const bracket = openCollection(schema, tokens);

    return {
        tokens,
        segment: currentSegment(bracket ? tokens.slice(bracket.open + 1) : tokens),
    };
}

/** The number slot at the caret, when it belongs to a unit-bearing field or key. */
function numberSlot(segment: Token[], unit: string | undefined): Slot | null {
    if (!unit) {
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

    return { unit, valueStart: segment[index].start };
}

/**
 * The unit-bearing number slot at the caret, when the caret is right after a
 * field or element number: `exif.FocalLength >= 35` or
 * `objects [confidence >= 80] has any`.
 */
export function unitSlot(schema: RuleSchema, text: string, caret: number): Slot | null {
    const { tokens, segment } = localSegment(schema, text, caret);
    const first = segment[0];

    if (!first || first.kind !== "word") {
        return null;
    }

    const bracket = openCollection(schema, tokens);

    if (bracket) {
        const element = elementFor(bracket.collection, first.text);

        if (!element || element.kind !== "number") {
            return null;
        }

        const slot = numberSlot(segment, element.unit);

        return slot ? { ...slot, element } : null;
    }

    const field = fieldFor(schema, first.text);

    if (!field || field.kind !== "number") {
        return null;
    }

    // A value inside a list is not a plain number slot.
    if (segment.some((token) => token.kind === "punct" && token.text === "[")) {
        return null;
    }

    const slot = numberSlot(segment, field.unit);

    return slot ? { ...slot, field } : null;
}

/**
 * Keep the unit attached to the number being typed. The editor arms this right
 * after an operator is picked, so it runs once per slot; the position checks
 * keep a second pass from stacking the unit.
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

/** Whether the caret sits right after the operator of a text-like value. */
function textSlot(schema: RuleSchema, text: string, caret: number): boolean {
    const { tokens, segment } = localSegment(schema, text, caret);

    if (segment.length !== 2) {
        return false;
    }

    const [first, second] = segment;

    if (first.kind !== "word" || !isOperator(second) || second.text.toLowerCase() === "in") {
        return false;
    }

    const bracket = openCollection(schema, tokens);

    if (bracket) {
        const element = elementFor(bracket.collection, first.text);

        return !!element && TEXT_KINDS.has(element.kind);
    }

    const field = fieldFor(schema, first.text);

    return !!field && TEXT_KINDS.has(field.kind);
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
