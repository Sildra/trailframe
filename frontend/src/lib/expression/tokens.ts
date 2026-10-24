/** Tokens and source positions of the local rule-expression language. */

export type TokenKind = "word" | "string" | "number" | "date" | "operator" | "punct" | "unknown" | "eof";

export interface Token {
    kind: TokenKind;
    /** The decoded text (strings lose their quotes and escapes). */
    text: string;
    /** The exact source slice. */
    raw: string;
    /** Start offset in UTF-16 code units. */
    start: number;
    /** End offset in UTF-16 code units (exclusive). */
    end: number;
}

export interface ParseIssue {
    message: string;
    start: number;
    end: number;
}

const WORD_START = /[A-Za-z_]/;
const WORD_PART = /[A-Za-z0-9_.]/;
const DIGIT = /[0-9]/;

/** Tokenize an expression. Never throws: bad input becomes `unknown` tokens. */
export function tokenize(source: string): { tokens: Token[]; issues: ParseIssue[] } {
    const tokens: Token[] = [];
    const issues: ParseIssue[] = [];
    let index = 0;

    const push = (kind: TokenKind, text: string, start: number, end: number, raw = source.slice(start, end)) => {
        tokens.push({ kind, text, raw, start, end });
    };

    while (index < source.length) {
        const start = index;
        const character = source[index];

        if (/\s/.test(character)) {
            index += 1;
            continue;
        }

        if (character === '"') {
            index += 1;
            let text = "";
            let closed = false;

            while (index < source.length) {
                const current = source[index];

                if (current === "\\") {
                    const next = source[index + 1];

                    if (next === undefined) {
                        index += 1;
                        break;
                    }

                    const escapes: Record<string, string> = { n: "\n", t: "\t", r: "\r", '"': '"', "\\": "\\" };
                    text += escapes[next] ?? next;
                    index += 2;
                    continue;
                }

                if (current === '"') {
                    index += 1;
                    closed = true;
                    break;
                }

                text += current;
                index += 1;
            }

            if (!closed) {
                issues.push({ message: "Unterminated string", start, end: index });
            }

            push("string", text, start, index);
            continue;
        }

        // Dates come before numbers so `2024-05-01` stays one token.
        const date = /^\d{4}-\d{2}-\d{2}/.exec(source.slice(index));

        if (date) {
            index += date[0].length;
            push("date", date[0], start, index);
            continue;
        }

        if (DIGIT.test(character) || (character === "-" && DIGIT.test(source[index + 1] ?? ""))) {
            const number = /^-?\d+(?:\.\d+)?/.exec(source.slice(index));

            if (number) {
                index += number[0].length;
                push("number", number[0], start, index);
                continue;
            }
        }

        if (WORD_START.test(character)) {
            index += 1;

            while (index < source.length && WORD_PART.test(source[index])) {
                index += 1;
            }

            push("word", source.slice(start, index), start, index);
            continue;
        }

        const two = source.slice(index, index + 2);

        if (two === ">=" || two === "<=" || two === "!=") {
            index += 2;
            push("operator", two, start, index);
            continue;
        }

        if (character === "!" && source.startsWith("!contains", index)) {
            index += "!contains".length;
            push("operator", "!contains", start, index);
            continue;
        }

        if (character === "=" || character === ">" || character === "<") {
            index += 1;
            push("operator", character, start, index);
            continue;
        }

        if (character === "(" || character === ")" || character === "[" || character === "]" || character === ",") {
            index += 1;
            push("punct", character, start, index);
            continue;
        }

        index += 1;
        push("unknown", character, start, index);
        issues.push({ message: `Unexpected character '${character}'`, start, end: index });
    }

    tokens.push({ kind: "eof", text: "", raw: "", start: source.length, end: source.length });

    return { tokens, issues };
}
