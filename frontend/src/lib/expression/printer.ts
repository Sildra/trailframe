import type {
    Condition,
    Definition,
    DetectionCondition,
    GroupCondition,
    MatchMode,
    MetricConstraint,
    ScalarCondition,
    ScalarOperator,
} from "../rules";
import { fieldFor, type RuleSchema } from "./schema";
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

function printValue(value: unknown, unit?: string): string {
    if (typeof value === "string") {
        return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : quote(value);
    }

    if (typeof value === "number") {
        return withUnit(String(value), unit);
    }

    if (typeof value === "boolean") {
        return String(value);
    }

    if (Array.isArray(value)) {
        return `[${value.map((item) => printValue(item)).join(", ")}]`;
    }

    return quote("");
}

/** Write a number with its unit: `80%`, `35mm`, `f/2.8`. */
function withUnit(value: string, unit: string | undefined): string {
    if (!unit) {
        return value;
    }

    return isPrefixUnit(unit) ? `${unit}${value}` : `${value}${unit}`;
}

function printMetric(metric: MetricConstraint, schema?: RuleSchema): string {
    const unit = schema
        ? schema.detection.metrics.find((item) => item.name === metric.name)?.unit
        : "%";

    return `${metric.name} ${OPERATOR_TOKENS[metric.op]} ${withUnit(String(metric.value), unit)}`;
}

function printDetection(condition: DetectionCondition, schema?: RuleSchema): string {
    const parts = ["objects"];

    if (condition.label || condition.op === "absent") {
        parts.push(condition.op === "absent" ? "has no" : "has", quote(condition.label));
    }

    if (condition.metrics.length > 0) {
        parts.push("with", condition.metrics.map((metric) => printMetric(metric, schema)).join(", "));
    }

    return parts.join(" ");
}

function printScalar(condition: ScalarCondition, schema?: RuleSchema): string {
    if (typeof condition.value === "boolean" && (condition.op === "eq" || condition.op === "neq")) {
        return `${condition.path} is ${condition.op === "neq" ? "not " : ""}${condition.value}`;
    }

    const unit = schema ? fieldFor(schema, condition.path)?.unit : undefined;

    return `${condition.path} ${OPERATOR_TOKENS[condition.op]} ${printValue(condition.value, unit)}`;
}

function printGroup(match: MatchMode, conditions: Condition[], schema?: RuleSchema): string {
    const rendered = conditions.map((condition) => {
        if (condition.type === "group") {
            return `(${printGroup(condition.match, condition.conditions, schema)})`;
        }

        if (condition.type === "detection") {
            return printDetection(condition, schema);
        }

        return printScalar(condition, schema);
    });

    return rendered.join(match === "any" ? " or " : " and ");
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

    if (condition.type === "detection") {
        return printDetection(condition, schema);
    }

    return printScalar(condition, schema);
}
