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

function printValue(value: unknown): string {
    if (typeof value === "string") {
        return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : quote(value);
    }

    if (typeof value === "number" || typeof value === "boolean") {
        return String(value);
    }

    if (Array.isArray(value)) {
        return `[${value.map((item) => printValue(item)).join(", ")}]`;
    }

    return quote("");
}

function printMetric(metric: MetricConstraint): string {
    return `${metric.name} ${OPERATOR_TOKENS[metric.op]} ${metric.value}`;
}

function printDetection(condition: DetectionCondition): string {
    const parts = ["objects"];

    if (condition.label || condition.op === "absent") {
        parts.push(condition.op === "absent" ? "has no" : "has", quote(condition.label));
    }

    if (condition.metrics.length > 0) {
        parts.push("with", condition.metrics.map(printMetric).join(", "));
    }

    return parts.join(" ");
}

function printScalar(condition: ScalarCondition): string {
    if (typeof condition.value === "boolean" && (condition.op === "eq" || condition.op === "neq")) {
        return `${condition.path} is ${condition.op === "neq" ? "not " : ""}${condition.value}`;
    }

    return `${condition.path} ${OPERATOR_TOKENS[condition.op]} ${printValue(condition.value)}`;
}

function printGroup(match: MatchMode, conditions: Condition[]): string {
    const rendered = conditions.map((condition) => {
        if (condition.type === "group") {
            return `(${printGroup(condition.match, condition.conditions)})`;
        }

        if (condition.type === "detection") {
            return printDetection(condition);
        }

        return printScalar(condition);
    });

    return rendered.join(match === "any" ? " or " : " and ");
}

/** Render an AST back to the expression language. */
export function printDefinition(definition: Definition): string {
    if (definition.conditions.length === 0) {
        return "";
    }

    return printGroup(definition.match, definition.conditions);
}

/** The expression text of a single condition. */
export function printCondition(condition: Condition): string {
    if (condition.type === "group") {
        return printGroup(condition.match, (condition as GroupCondition).conditions);
    }

    if (condition.type === "detection") {
        return printDetection(condition);
    }

    return printScalar(condition);
}
