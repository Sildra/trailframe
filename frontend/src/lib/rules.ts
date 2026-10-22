import type { components } from "../api/generated/schema";

export type TagRule = components["schemas"]["TagRuleResponse"];
export type TagRuleField = components["schemas"]["TagRuleField"];
export type TagRuleTestMatch = components["schemas"]["TagRuleTestMatch"];

export type RuleOperator = "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "contains" | "in" | "present" | "absent";

export interface RuleConstraint {
    op: RuleOperator;
    value: string;
}

export interface RuleCondition {
    /** The metadata field the condition reads. */
    field: string;
    /** The operator, as named by the field catalog. */
    operator: RuleOperator;
    /** The value compared against, for the operators that take one. */
    value: string;
    /** The detected label, for the `objects` field. */
    match_label: string;
    /** The per-metric constraints, for the `objects` field. */
    constraints: Record<string, RuleConstraint>;
}

export interface RuleDraft {
    id: number | null;
    name: string;
    enabled: boolean;
    priority: number;
    description: string;
    /** How the conditions combine: `and` or `or`. */
    operator: "and" | "or";
    conditions: RuleCondition[];
    tags: string[];
}

export const EMPTY_CONDITION: RuleCondition = {
    field: "objects",
    operator: "present",
    value: "",
    match_label: "",
    constraints: {},
};

/** A blank rule, ready to be edited. */
export function emptyRule(): RuleDraft {
    return {
        id: null,
        name: "",
        enabled: true,
        priority: 0,
        description: "",
        operator: "and",
        conditions: [{ ...EMPTY_CONDITION }],
        tags: [],
    };
}

/** Read a stored rule into the editable draft. */
export function toDraft(rule: TagRule): RuleDraft {
    const conditions = rule.conditions ?? {};
    const children = Array.isArray(conditions.rules) ? conditions.rules : [];

    return {
        id: rule.id ?? null,
        name: rule.name ?? "",
        enabled: rule.enabled ?? true,
        priority: rule.priority ?? 0,
        description: rule.description ?? "",
        operator: conditions.operator === "or" ? "or" : "and",
        conditions: children.map((child) => toCondition(child)),
        tags: rule.tags ?? [],
    };
}

/** Read a stored condition into the editable form. */
export function toCondition(raw: unknown): RuleCondition {
    const child = (raw ?? {}) as Record<string, unknown>;
    const constraints: Record<string, RuleConstraint> = {};
    const rawConstraints = (child.constraints ?? {}) as Record<string, Record<string, unknown>>;

    for (const [metric, constraint] of Object.entries(rawConstraints)) {
        const [op, value] = Object.entries(constraint ?? {})[0] ?? [];

        if (op) {
            constraints[metric] = { op: op as RuleOperator, value: String(value ?? "") };
        }
    }

    return {
        field: String(child.field ?? "objects"),
        operator: (child.operator as RuleOperator) ?? "present",
        value: child.value === undefined || child.value === null ? "" : String(child.value),
        match_label: child.match_label === undefined || child.match_label === null ? "" : String(child.match_label),
        constraints,
    };
}

/** The payload sent to the API for a draft. */
export function toPayload(draft: RuleDraft) {
    return {
        name: draft.name.trim(),
        enabled: draft.enabled,
        priority: draft.priority,
        description: draft.description.trim() || null,
        conditions: {
            operator: draft.operator,
            rules: draft.conditions.map((condition) => {
                const base: Record<string, unknown> = {
                    field: condition.field,
                    operator: condition.operator,
                };

                if (condition.value !== "") {
                    base.value = condition.value;
                }

                if (condition.field === "objects") {
                    base.match_label = condition.match_label.trim().toLowerCase();
                    base.constraints = Object.fromEntries(
                        Object.entries(condition.constraints)
                            .filter(([, constraint]) => constraint.value !== "")
                            .map(([metric, constraint]) => [metric, { [constraint.op]: constraint.value }]),
                    );
                }

                return base;
            }),
        },
        tags: draft.tags,
    };
}

/** The field catalog, grouped for the builder. */
export function groupFields(fields: TagRuleField[]): { group: string; fields: TagRuleField[] }[] {
    const groups = new Map<string, TagRuleField[]>();

    for (const field of fields) {
        const list = groups.get(field.group) ?? [];

        list.push(field);
        groups.set(field.group, list);
    }

    return [...groups.entries()].map(([group, items]) => ({ group, fields: items }));
}

/** The catalog entry of a field, when the builder knows it. */
export function findField(fields: TagRuleField[], name: string): TagRuleField | undefined {
    return fields.find((field) => field.field === name);
}

/** The operators offered for a field, falling back to equality. */
export function fieldOperators(field: TagRuleField | undefined): { op: string; label: string }[] {
    if (!field || field.operators.length === 0) {
        return [{ op: "eq", label: "is" }];
    }

    return field.operators as { op: string; label: string }[];
}

/** A readable summary of a condition, used in the rule list. */
export function describeCondition(condition: RuleCondition, fields: TagRuleField[]): string {
    const field = findField(fields, condition.field);
    const operator = fieldOperators(field).find((entry) => entry.op === condition.operator);

    if (condition.field === "objects") {
        const label = condition.match_label || "any object";
        const parts: string[] = [];

        for (const [metric, constraint] of Object.entries(condition.constraints)) {
            parts.push(`${metric} ${constraint.op} ${constraint.value}`);
        }

        return parts.length > 0 ? `${label} (${parts.join(", ")})` : label;
    }

    const operatorLabel = operator?.label ?? condition.operator;

    return `${field?.label ?? condition.field} ${operatorLabel} ${condition.value}`.trim();
}

/** A readable summary of a whole rule. */
export function describeRule(draft: RuleDraft, fields: TagRuleField[]): string {
    if (draft.conditions.length === 0) {
        return "No condition";
    }

    const parts = draft.conditions.map((condition) => describeCondition(condition, fields));

    return parts.join(draft.operator === "or" ? " or " : " and ");
}
