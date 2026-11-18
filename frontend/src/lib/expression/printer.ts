import type {
    CollectionCondition,
    Condition,
    Definition,
    ElementCondition,
    GroupCondition,
    MatchMode,
    ScalarCondition,
    ScalarOperator,
} from "../rules";
import { collectionFor, elementFor, fieldFor, type RuleSchema, type SchemaCollection } from "./schema";
import { isPrefixUnit } from "./units";

const OPERATOR_TOKENS: Record<ScalarOperator, string> = {
    eq: "=",
    neq: "!=",
    gt: ">",
    gte: ">=",
    lt: "<",
    lte: "<=",
    contains: "contains",
    not_contains: "!contains",
    in: "in",
};

function quote(value: string): string {
    return JSON.stringify(value);
}

/** Trim the float noise of a unit conversion (`0.07 * 100` is `7.000000000000001`). */
function round(value: number): number {
    return Number(value.toFixed(6));
}

/**
 * Write a number with its declared unit. `%` is the only semantic unit: the AST
 * stores the fraction, so it is multiplied back to the 0–100 scale on print.
 */
function numberText(value: number, unit?: string): string {
    if (unit === "%") {
        return `${round(value * 100)}%`;
    }

    const text = String(round(value));

    if (!unit) {
        return text;
    }

    return isPrefixUnit(unit) ? `${unit}${text}` : `${text}${unit}`;
}

function printValue(value: unknown, unit?: string): string {
    if (typeof value === "string") {
        return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : quote(value);
    }

    if (typeof value === "number") {
        return numberText(value, unit);
    }

    if (typeof value === "boolean") {
        return String(value);
    }

    if (Array.isArray(value)) {
        return `[${value.map((item) => printValue(item)).join(", ")}]`;
    }

    return quote("");
}

function printElement(condition: ElementCondition, collection: SchemaCollection | undefined): string {
    const unit = collection ? elementFor(collection, condition.key)?.unit : undefined;

    if (typeof condition.value === "boolean" && (condition.op === "eq" || condition.op === "neq")) {
        return `${condition.key} is ${condition.op === "neq" ? "not " : ""}${condition.value}`;
    }

    return `${condition.key} ${OPERATOR_TOKENS[condition.op]} ${printValue(condition.value, unit)}`;
}

function printElementExpression(condition: Condition, collection: SchemaCollection | undefined): string {
    if (condition.type === "group") {
        return printElementGroup(condition.match, condition.conditions, collection);
    }

    if (condition.type !== "element") {
        return "";
    }

    return printElement(condition, collection);
}

function printElementGroup(
    match: MatchMode,
    conditions: Condition[],
    collection: SchemaCollection | undefined,
): string {
    const rendered = conditions.map((condition) =>
        condition.type === "group"
            ? `(${printElementGroup(condition.match, condition.conditions, collection)})`
            : printElementExpression(condition, collection),
    );

    return rendered.join(match === "any" ? " or " : " and ");
}

function printCollection(condition: CollectionCondition, schema?: RuleSchema): string {
    const collection = schema ? collectionFor(schema, condition.path) : undefined;

    return `${condition.path} [${printElementExpression(condition.condition, collection)}] has ${condition.quantifier}`;
}

function printScalar(condition: ScalarCondition, schema?: RuleSchema): string {
    if (typeof condition.value === "boolean" && (condition.op === "eq" || condition.op === "neq")) {
        return `${condition.path} is ${condition.op === "neq" ? "not " : ""}${condition.value}`;
    }

    const unit = schema ? fieldFor(schema, condition.path)?.unit : undefined;

    return `${condition.path} ${OPERATOR_TOKENS[condition.op]} ${printValue(condition.value, unit)}`;
}

function printConditionInner(condition: Condition, schema?: RuleSchema): string {
    if (condition.type === "group") {
        return `(${printGroup(condition.match, condition.conditions, schema)})`;
    }

    if (condition.type === "collection") {
        return printCollection(condition, schema);
    }

    if (condition.type === "element") {
        return printElement(condition, undefined);
    }

    return printScalar(condition, schema);
}

function printGroup(match: MatchMode, conditions: Condition[], schema?: RuleSchema): string {
    return conditions.map((condition) => printConditionInner(condition, schema)).join(match === "any" ? " or " : " and ");
}

/** Render an AST back to the expression language. */
export function printDefinition(definition: Definition, schema?: RuleSchema): string {
    if (definition.conditions.length === 0) {
        return "";
    }

    return printGroup(definition.match, definition.conditions, schema);
}

/** The expression text of a single condition. */
export function printCondition(condition: Condition, schema?: RuleSchema): string {
    if (condition.type === "group") {
        return printGroup(condition.match, (condition as GroupCondition).conditions, schema);
    }

    return printConditionInner(condition, schema);
}
