import type { components } from "../api/generated/schema";

export type RuleResponse = components["schemas"]["RuleResponse"];

export type MatchMode = "all" | "any";
export type NumericOperator = "eq" | "neq" | "gt" | "gte" | "lt" | "lte";
export type ScalarOperator = NumericOperator | "contains" | "not_contains" | "in";
export type RuleOperator = ScalarOperator | "present" | "absent";

export type ScalarValue = string | number | boolean | string[] | null;

export interface MetricConstraint {
    name: string;
    op: NumericOperator;
    value: number;
}

export interface ScalarCondition {
    type: "scalar";
    path: string;
    op: ScalarOperator;
    value: ScalarValue;
}

export interface DetectionCondition {
    type: "detection";
    label: string;
    op: "present" | "absent";
    metrics: MetricConstraint[];
}

export interface GroupCondition {
    type: "group";
    match: MatchMode;
    conditions: Condition[];
}

export type Condition = ScalarCondition | DetectionCondition | GroupCondition;

export interface Definition {
    version: number;
    match: MatchMode;
    conditions: Condition[];
}

/** A rule as edited by the client, before it is saved. */
export interface RuleDraft {
    id: string | null;
    tag: string;
    name: string;
    description: string;
    enabled: boolean;
    priority: number;
    /** The expression text, kept for display and re-editing. */
    expression: string;
    /** The parsed definition; authoritative and validated locally. */
    definition: Definition;
}

export function emptyDefinition(): Definition {
    return { version: 1, match: "all", conditions: [] };
}

/** A blank rule for `tag`, ready to be edited. */
export function emptyRule(tag: string): RuleDraft {
    return {
        id: null,
        tag,
        name: "",
        description: "",
        enabled: true,
        priority: 0,
        expression: "",
        definition: emptyDefinition(),
    };
}

/** Read a stored rule into the editable draft. */
export function toDraft(rule: RuleResponse, fallbackExpression = ""): RuleDraft {
    return {
        id: rule.id ?? null,
        tag: rule.tag ?? "",
        name: rule.name ?? "",
        description: rule.description ?? "",
        enabled: rule.enabled ?? true,
        priority: rule.priority ?? 0,
        expression: rule.expression || fallbackExpression,
        definition: rule.definition as Definition,
    };
}

/** The payload sent to the API for a draft. */
export function toPayload(draft: RuleDraft) {
    return {
        tag: draft.tag,
        name: draft.name.trim(),
        description: draft.description,
        enabled: draft.enabled,
        priority: draft.priority,
        expression: draft.expression,
        definition: draft.definition,
    };
}

/** Count the leaf conditions of a definition. */
export function countConditions(definition: Definition): number {
    let total = 0;

    const walk = (conditions: Condition[]) => {
        for (const condition of conditions) {
            if (condition.type === "group") {
                walk(condition.conditions);
            } else {
                total += 1;
            }
        }
    };

    walk(definition.conditions);

    return total;
}
