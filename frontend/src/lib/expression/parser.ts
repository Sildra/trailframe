import type {
    Condition,
    Definition,
    DetectionCondition,
    MatchMode,
    MetricConstraint,
    NumericOperator,
    ScalarCondition,
    ScalarOperator,
    ScalarValue,
} from "../rules";
import { fieldFor, type RuleSchema } from "./schema";
import { tokenize, type ParseIssue, type Token } from "./tokens";
import { isKnownUnit, isPrefixUnit } from "./units";

const NUMERIC_OPS = new Set<NumericOperator>(["eq", "neq", "gt", "gte", "lt", "lte"]);

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

const NUMERIC_OPERATOR_BY_TOKEN: Record<string, NumericOperator> = {
    "=": "eq",
    "!=": "neq",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
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
    private readonly schema?: RuleSchema;

    constructor(tokens: Token[], schema?: RuleSchema) {
        this.tokens = tokens;
        this.schema = schema;
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

    /** The detection metric the schema describes, when it knows the name. */
    private metric(name: string) {
        return this.schema?.detection.metrics.find((metric) => metric.name === name);
    }

    /**
     * Read a number and its unit. Units are required when the schema declares
     * one (`35mm`, `f/2.8`, `80%`); without a schema they stay optional so old
     * expressions still parse.
     */
    private parseNumber(unit: string | undefined): number {
        const first = this.peek();

        if (first.kind === "unit" && isPrefixUnit(first.text)) {
            this.next();

            if (unit && first.text !== unit) {
                throw new ParseError(`Expected the unit '${unit}'`, first.start, first.end);
            }

            if (!unit && !isKnownUnit(first.text)) {
                throw new ParseError(`Unknown unit '${first.text}'`, first.start, first.end);
            }

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
            if (unit && suffix !== unit) {
                throw new ParseError(`Expected the unit '${unit}'`, next.start, next.end);
            }

            if (!unit && this.schema) {
                throw new ParseError(`Unexpected unit '${suffix}'`, next.start, next.end);
            }

            this.next();
        } else if (unit) {
            throw new ParseError(`Expected the unit '${unit}' after the number`, number.start, number.end);
        }

        return Number(number.text);
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

        return { version: 1, match: group.match, conditions: group.conditions };
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

        return { match: "all", conditions: [this.parsePredicate()] };
    }

    private parsePredicate(): Condition {
        const token = this.next();

        if (token.kind !== "word") {
            throw new ParseError("Expected a field name", token.start, token.end);
        }

        if (token.text.toLowerCase() === "objects") {
            return this.parseDetection();
        }

        return this.parseScalar(token.text);
    }

    private parseScalar(path: string): ScalarCondition {
        if (this.matchWord("is")) {
            const negated = this.matchWord("not");
            const value = this.parseValue(path);

            return { type: "scalar", path, op: negated ? "neq" : "eq", value };
        }

        const token = this.next();
        const op = token.kind === "operator" || token.kind === "word" ? OPERATOR_BY_TOKEN[token.text.toLowerCase()] : undefined;

        if (!op) {
            throw new ParseError(`Expected a comparison operator after '${path}'`, token.start, token.end);
        }

        const value = op === "in" ? this.parseList() : this.parseValue(path);

        return { type: "scalar", path, op, value };
    }

    /** A scalar value, reading the field's unit when the schema declares one. */
    private parseValue(path: string): ScalarValue {
        const field = this.schema ? fieldFor(this.schema, path) : undefined;

        if (field?.kind === "number") {
            return this.parseNumber(field.unit);
        }

        const first = this.peek();

        if (!this.schema && (first.kind === "number" || (first.kind === "unit" && isPrefixUnit(first.text)))) {
            return this.parseNumber(undefined);
        }

        return this.parseLiteral();
    }

    private parseDetection(): DetectionCondition {
        let op: "present" | "absent" = "present";
        let label = "";
        let metrics: MetricConstraint[] = [];

        if (this.matchWord("has")) {
            if (this.matchWord("no")) {
                op = "absent";
            }

            const token = this.peek();

            if (token.kind !== "string") {
                this.fail("Expected an object label in quotes");
            }

            label = this.next().text;
        }

        if (this.matchWord("with")) {
            metrics = this.parseMetrics();
        }

        return { type: "detection", label, op, metrics };
    }

    private parseMetrics(): MetricConstraint[] {
        const metrics: MetricConstraint[] = [];

        do {
            const name = this.next();

            if (name.kind !== "word") {
                throw new ParseError("Expected a metric name", name.start, name.end);
            }

            const token = this.next();
            const op = token.kind === "operator" ? NUMERIC_OPERATOR_BY_TOKEN[token.text] : undefined;

            if (!op || !NUMERIC_OPS.has(op)) {
                throw new ParseError(`Expected a numeric comparison after '${name.text}'`, token.start, token.end);
            }

            metrics.push({ name: name.text, op, value: this.parseNumber(this.metric(name.text)?.unit) });
        } while (this.matchPunct(","));

        return metrics;
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

        if (token.kind === "number") {
            return Number(token.text);
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

/** Parse an expression into the rule AST, collecting a readable issue. */
export function parseExpression(source: string, schema?: RuleSchema | null): ParseResult {
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
        return { definition: new Parser(tokens, schema ?? undefined).parse(), issues: [] };
    } catch (error) {
        if (error instanceof ParseError) {
            return { definition: null, issues: [{ message: error.message, start: error.start, end: error.end }] };
        }

        return { definition: null, issues: [{ message: "The expression could not be parsed", start: 0, end: source.length }] };
    }
}
