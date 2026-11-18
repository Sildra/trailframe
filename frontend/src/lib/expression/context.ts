/** Shared caret context for the hints and the typing aids. */

import { collectionFor, type RuleSchema, type SchemaCollection } from "./schema";
import type { Token } from "./tokens";

export interface CollectionContext {
    /** Index of the opening `[` in the token list. */
    open: number;
    path: string;
    collection: SchemaCollection;
}

/**
 * The collection filter the caret sits in, when any: the last unmatched `[`
 * that follows a declared collection path. List brackets (`in [...]`) are
 * ignored because the token before them is an operator.
 */
export function openCollection(schema: RuleSchema, tokens: Token[]): CollectionContext | null {
    let depth = 0;
    let context: CollectionContext | null = null;

    tokens.forEach((token, index) => {
        if (token.kind !== "punct") {
            return;
        }

        if (token.text === "[") {
            const before = tokens[index - 1];
            const collection = before?.kind === "word" ? collectionFor(schema, before.text) : undefined;

            if (collection) {
                depth += 1;
                context = { open: index, path: collection.path, collection };
            }
        } else if (token.text === "]" && depth > 0) {
            depth -= 1;

            if (depth === 0) {
                context = null;
            }
        }
    });

    return depth > 0 ? context : null;
}

/**
 * The tokens of the condition the caret sits in (after the last and/or/( at
 * the current bracket depth). Joiners inside a collection filter belong to the
 * filter, not to the condition around it.
 */
export function currentSegment(tokens: Token[]): Token[] {
    let start = 0;
    let depth = 0;

    tokens.forEach((token, index) => {
        if (token.kind === "punct" && token.text === "[") {
            depth += 1;
            return;
        }

        if (token.kind === "punct" && token.text === "]") {
            depth = Math.max(0, depth - 1);
            return;
        }

        if (depth > 0) {
            return;
        }

        const isJoiner = token.kind === "word" && ["and", "or"].includes(token.text.toLowerCase());
        const isGroup = token.kind === "punct" && token.text === "(";

        if (isJoiner || isGroup) {
            start = index + 1;
        }
    });

    return tokens.slice(start);
}
