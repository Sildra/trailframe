import type {
    CollectionCondition,
    Condition,
    Definition,
    ElementCondition,
    MatchMode,
    Quantifier,
    ScalarCondition,
    ScalarOperator,
    ScalarValue,
} from "../rules";
import { tokenize, type ParseIssue, type Token } from "./tokens";
import { isKnownUnit, isPrefixUnit } from "./units";

const QUANTIFIERS = new Set<Quantifier>(["any", "none", "one", "all"]);

const OPERATOR_BY_TOKEN: Record<string, ScalarOperator> = {
    "=": "eq",
    "!=": "neq",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
    contains: "contains",
    "!contains": "not_contains",
    in: "in",
};

/** How `not` flips a comparison; `in` has no inverse operator. */
const NEGATED_OPERATOR: Record<ScalarOperator, ScalarOperator | null> = {
    eq: "neq",
    neq: "eq",
    gt: "lte",
    gte: "lt",
    lt: "gte",
    lte: "gt",
    contains: "not_contains",
    not_contains: "contains",
    in: null,
};

interface Group {
    match: MatchMode;
    conditions: Condition[];
}

class ParseError extends Error {
    readonly start: number;
    readonly end: number;

    constructor(message: string, start: number, end: number) {
        super(message);
        this.start = start;
        this.end = end;
    }
}

class Parser {
    private index = 0;
    private readonly tokens: Token[];

    constructor(tokens: Token[]) {
        this.tokens = tokens;
    }

    private peek(offset = 0): Token {
        return this.tokens[Math.min(this.index + offset, this.tokens.length - 1)];
    }

    private next(): Token {
        const token = this.peek();
        this.index += 1;

        return token;
    }

    private matchWord(...words: string[]): boolean {
        const token = this.peek();

        if (token.kind === "word" && words.includes(token.text.toLowerCase())) {
            this.index += 1;
            return true;
        }

        return false;
    }

    private matchPunct(value: string): boolean {
        if (this.peek().kind === "punct" && this.peek().text === value) {
            this.index += 1;
            return true;
        }

        return false;
    }

    private expectPunct(value: string): void {
        if (!this.matchPunct(value)) {
            this.fail(`Expected '${value}'`);
        }
    }

    private fail(message: string): never {
        const token = this.peek();

        throw new ParseError(message, token.start, token.end);
    }

    /**
     * Read a number and its optional unit. Units are generic sugar: `%` divides
     * by 100 at parse time (so the AST holds the stored fraction), every other
     * unit is ignored. The unit may be written before the number (`f/2.8`) or
     * after it (`80%`, `35mm`).
     */
    private parseNumber(): number {
        const first = this.peek();

        if (first.kind === "unit" && isPrefixUnit(first.text)) {
            this.next();

            const number = this.next();

            if (number.kind !== "number") {
                throw new ParseError("Expected a number after the unit", number.start, number.end);
            }

            return Number(number.text);
        }

        const number = this.next();

        if (number.kind !== "number") {
            throw new ParseError("Expected a number", number.start, number.end);
        }

        const next = this.peek();
        const suffix =
            next.kind === "unit" || (next.kind === "word" && isKnownUnit(next.text)) ? next.text : undefined;

        if (suffix !== undefined) {
            this.next();
        }

        const value = Number(number.text);

        return suffix === "%" ? value / 100 : value;
    }

    private asCondition(group: Group): Condition {
        if (group.conditions.length === 1) {
            return group.conditions[0];
        }

        return { type: "group", match: group.match, conditions: group.conditions };
    }

    parse(): Definition {
        const group = this.parseOr();
        const token = this.peek();

        if (token.kind !== "eof") {
            this.fail(`Unexpected '${token.raw || "end"}'`);
        }

        return { version: 2, match: group.match, conditions: group.conditions };
    }

    private parseOr(): Group {
        const items: Group[] = [this.parseAnd()];

        while (this.matchWord("or")) {
            items.push(this.parseAnd());
        }

        if (items.length === 1) {
            return items[0];
        }

        return { match: "any", conditions: items.map((item) => this.asCondition(item)) };
    }

    private parseAnd(): Group {
        const items: Group[] = [this.parseUnary()];

        while (this.matchWord("and")) {
            items.push(this.parseUnary());
        }

        if (items.length === 1) {
            return items[0];
        }

        return { match: "all", conditions: items.map((item) => this.asCondition(item)) };
    }

    private parseUnary(): Group {
        if (this.matchPunct("(")) {
            const group = this.parseOr();
            this.expectPunct(")");

            return group;
        }

        if (this.matchWord("not")) {
            return this.negate(this.parseUnary());
        }

        return { match: "all", conditions: [this.parsePredicate()] };
    }

    private parsePredicate(): Condition {
        const token = this.next();

        if (token.kind !== "word") {
            throw new ParseError("Expected a field name", token.start, token.end);
        }

        // `path [ … ] has <quantifier>` is the only bracket form; anything else
        // is a scalar comparison.
        if (this.peek().kind === "punct" && this.peek().text === "[") {
            return this.parseCollection(token.text);
        }

        return this.parseScalar(token.text);
    }

    private parseScalar(path: string): ScalarCondition {
        const { op, value } = this.parseComparison(path);

        return { type: "scalar", path, op, value };
    }

    private parseCollection(path: string): CollectionCondition {
        this.expectPunct("[");

        const condition = this.parseElementOr();
        this.expectPunct("]");

        if (!this.matchWord("has")) {
            this.fail("Expected 'has' after the filter");
        }

        const token = this.next();
        const quantifier = token.kind === "word" ? token.text.toLowerCase() : "";

        if (!QUANTIFIERS.has(quantifier as Quantifier)) {
            throw new ParseError("Expected any, none, one or all", token.start, token.end);
        }

        return {
            type: "collection",
            path,
            quantifier: quantifier as Quantifier,
            condition: this.asCondition(condition),
        };
    }

    private parseElementOr(): Group {
        const items: Group[] = [this.parseElementAnd()];

        while (this.matchWord("or")) {
            items.push(this.parseElementAnd());
        }

        if (items.length === 1) {
            return items[0];
        }

        return { match: "any", conditions: items.map((item) => this.asCondition(item)) };
    }

    private parseElementAnd(): Group {
        const items: Group[] = [this.parseElementUnary()];

        while (this.matchWord("and")) {
            items.push(this.parseElementUnary());
        }

        if (items.length === 1) {
            return items[0];
        }

        return { match: "all", conditions: items.map((item) => this.asCondition(item)) };
    }

    private parseElementUnary(): Group {
        if (this.matchPunct("(")) {
            const group = this.parseElementOr();
            this.expectPunct(")");

            return group;
        }

        if (this.matchWord("not")) {
            return this.negate(this.parseElementUnary());
        }

        return { match: "all", conditions: [this.parseElement()] };
    }

    private parseElement(): ElementCondition {
        const token = this.next();

        if (token.kind !== "word") {
            throw new ParseError("Expected an element key", token.start, token.end);
        }

        const { op, value } = this.parseComparison(token.text);

        return { type: "element", key: token.text, op, value };
    }

    /** The operator and operand after a field path or an element key. */
    private parseComparison(label: string): { op: ScalarOperator; value: ScalarValue } {
        if (this.matchWord("is")) {
            const negated = this.matchWord("not");

            return { op: negated ? "neq" : "eq", value: this.parseValue() };
        }

        const token = this.next();
        const op = token.kind === "operator" || token.kind === "word" ? OPERATOR_BY_TOKEN[token.text.toLowerCase()] : undefined;

        if (!op) {
            throw new ParseError(`Expected a comparison operator after '${label}'`, token.start, token.end);
        }

        return { op, value: op === "in" ? this.parseList() : this.parseValue() };
    }

    /** Push `not` down to the leaves: the AST has no negation node. */
    private negate(group: Group): Group {
        const conditions = group.conditions.map((condition) => this.negateCondition(condition));

        if (conditions.length === 1) {
            return { match: "all", conditions };
        }

        return { match: group.match === "any" ? "all" : "any", conditions };
    }

    private negateCondition(condition: Condition): Condition {
        if (condition.type === "group") {
            const negated = this.negate(condition);

            return negated.conditions.length === 1 ? negated.conditions[0] : { type: "group", ...negated };
        }

        if (condition.type === "collection") {
            throw new ParseError(
                "Use 'has none' (or 'has any') instead of 'not' before a collection",
                this.peek().start,
                this.peek().end,
            );
        }

        const op = NEGATED_OPERATOR[condition.op];

        if (op !== null) {
            return { ...condition, op };
        }

        // `not (path in [a, b])` becomes `path != a and path != b`.
        const values = Array.isArray(condition.value) ? condition.value : [condition.value];

        return {
            type: "group",
            match: "all",
            conditions: values.map((value) => ({ ...condition, op: "neq" as const, value })),
        };
    }

    private parseValue(): ScalarValue {
        const first = this.peek();

        if (first.kind === "number" || (first.kind === "unit" && isPrefixUnit(first.text))) {
            return this.parseNumber();
        }

        return this.parseLiteral();
    }

    private parseList(): ScalarValue {
        this.expectPunct("[");
        const values: string[] = [];

        if (!this.matchPunct("]")) {
            do {
                const token = this.next();

                if (token.kind !== "string" && token.kind !== "date" && token.kind !== "number") {
                    throw new ParseError("Expected a value inside the list", token.start, token.end);
                }

                values.push(token.text);
            } while (this.matchPunct(","));

            this.expectPunct("]");
        }

        return values;
    }

    private parseLiteral(): ScalarValue {
        const token = this.next();

        if (token.kind === "string" || token.kind === "date") {
            return token.text;
        }

        if (token.kind === "word") {
            const word = token.text.toLowerCase();

            if (word === "true") {
                return true;
            }

            if (word === "false") {
                return false;
            }
        }

        throw new ParseError("Expected a value", token.start, token.end);
    }
}

export interface ParseResult {
    definition: Definition | null;
    issues: ParseIssue[];
}

/**
 * Parse an expression into the rule AST, collecting a readable issue.
 *
 * Parsing is schema-free: a collection is recognised by its `[` filter, and
 * units are optional. The schema is only needed to validate or print.
 */
export function parseExpression(source: string): ParseResult {
    const text = source.trim();

    if (!text) {
        return { definition: null, issues: [{ message: "The expression is empty", start: 0, end: source.length }] };
    }

    const { issues: lexIssues } = tokenize(source);

    if (lexIssues.length > 0) {
        return { definition: null, issues: lexIssues };
    }

    const { tokens } = tokenize(source);

    try {
        return { definition: new Parser(tokens).parse(), issues: [] };
    } catch (error) {
        if (error instanceof ParseError) {
            return { definition: null, issues: [{ message: error.message, start: error.start, end: error.end }] };
        }

        return { definition: null, issues: [{ message: "The expression could not be parsed", start: 0, end: source.length }] };
    }
}
