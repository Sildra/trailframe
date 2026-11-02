import type { Condition, Definition, NumericOperator, ScalarOperator } from "../rules";

export type FieldKind = "detection" | "text" | "number" | "date" | "bool" | "enum" | "list";

export interface ValueSource {
    source: "none" | "static" | "distinct" | "objects" | "tags" | "scanners";
    values: string[];
}

export interface SchemaMetric {
    name: string;
    label: string;
    description: string;
    kind: "number";
    operators: NumericOperator[];
    min: number;
    max: number;
    step: number;
    unit?: string;
}

export interface SchemaDetection {
    path: string;
    label_field: string;
    label_values: ValueSource;
    operators: ("present" | "absent")[];
    metrics: SchemaMetric[];
}

export interface SchemaField {
    path: string;
    group: string;
    label: string;
    description: string;
    kind: FieldKind;
    operators: ScalarOperator[] | ("present" | "absent")[];
    computed: boolean;
    values: ValueSource;
    min?: number;
    max?: number;
    step?: number;
    unit?: string;
    detection?: {
        label_field: string;
        label_values: ValueSource;
        operators: ("present" | "absent")[];
        metrics: SchemaMetric[];
    };
}

export interface SchemaGroup {
    name: string;
    label: string;
    fields: SchemaField[];
}

export interface SchemaOperator {
    name: string;
    token: string;
    label: string;
    doc: string;
}

export interface RuleSchema {
    version: number;
    capabilities: string[];
    grammar: {
        keywords: { token: string; kind: string; doc: string }[];
        operators: Record<string, SchemaOperator>;
    };
    detection: SchemaDetection;
    groups: SchemaGroup[];
}

export interface ValidationIssue {
    message: string;
}

export const MAX_CONDITIONS = 20;
export const MAX_GROUP_DEPTH = 4;

/** Every field of the schema, flattened. */
export function schemaFields(schema: RuleSchema): SchemaField[] {
    return schema.groups.flatMap((group) => group.fields);
}

/** The schema field at `path`, when it exists. */
export function fieldFor(schema: RuleSchema, path: string): SchemaField | undefined {
    return schemaFields(schema).find((field) => field.path === path);
}

/** The operator label the editor shows for a field. */
export function operatorLabel(schema: RuleSchema, name: string): string {
    return schema.grammar.operators[name]?.label ?? name;
}

/** The operator token the expression uses. */
export function operatorToken(schema: RuleSchema, name: string): string {
    return schema.grammar.operators[name]?.token ?? name;
}

/** A field uses its detection spec when it is the object field. */
export function detectionFor(schema: RuleSchema, field: SchemaField) {
    return field.detection ?? (field.path === schema.detection.path ? schema.detection : undefined);
}

function issue(message: string): ValidationIssue {
    return { message };
}

function isNumber(value: unknown): value is number {
    return typeof value === "number" && Number.isFinite(value);
}

function isDate(value: unknown): boolean {
    return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value));
}

function validateScalar(schema: RuleSchema, condition: Extract<Condition, { type: "scalar" }>): ValidationIssue[] {
    const field = fieldFor(schema, condition.path);

    if (!field) {
        return [issue(`Unknown field '${condition.path}'`)];
    }

    if (!(field.operators as string[]).includes(condition.op)) {
        return [issue(`'${condition.op}' cannot be used on '${condition.path}'`)];
    }

    if (condition.op === "in") {
        if (!Array.isArray(condition.value) || condition.value.length === 0) {
            return [issue("'in' needs a non-empty list of values")];
        }

        if (field.kind === "number" && condition.value.some((item) => !isNumber(Number(item)))) {
            return [issue(`'${condition.path}' needs a list of numbers`)];
        }

        return [];
    }

    if (field.kind === "number" && !isNumber(condition.value)) {
        return [issue(`'${condition.path}' needs a number`)];
    }

    if (field.kind === "date" && !isDate(condition.value)) {
        return [issue(`'${condition.path}' needs a YYYY-MM-DD date`)];
    }

    if (field.kind === "bool" && typeof condition.value !== "boolean") {
        return [issue(`'${condition.path}' needs true or false`)];
    }

    if ((field.kind === "text" || field.kind === "enum" || field.kind === "list") && typeof condition.value !== "string") {
        return [issue(`'${condition.path}' needs text`)];
    }

    return [];
}

function validateDetection(schema: RuleSchema, condition: Extract<Condition, { type: "detection" }>): ValidationIssue[] {
    const metrics = new Map(schema.detection.metrics.map((metric) => [metric.name, metric]));
    const issues: ValidationIssue[] = [];

    for (const metric of condition.metrics) {
        const spec = metrics.get(metric.name);

        if (!spec) {
            issues.push(issue(`Unknown object metric '${metric.name}'`));
            continue;
        }

        if (!isNumber(metric.value)) {
            issues.push(issue(`'${metric.name}' needs a number`));
            continue;
        }

        if (metric.value < spec.min || metric.value > spec.max) {
            issues.push(issue(`'${metric.name}' must be between ${spec.min} and ${spec.max}`));
        }
    }

    return issues;
}

function validateConditions(schema: RuleSchema, conditions: Condition[], depth: number, issues: ValidationIssue[]): number {
    if (depth > MAX_GROUP_DEPTH) {
        issues.push(issue(`Groups can nest at most ${MAX_GROUP_DEPTH} levels`));
        return 0;
    }

    let total = 0;

    for (const condition of conditions) {
        if (condition.type === "group") {
            if (condition.conditions.length === 0) {
                issues.push(issue("Every group needs at least one condition"));
            }

            total += validateConditions(schema, condition.conditions, depth + 1, issues);
        } else {
            total += 1;

            if (condition.type === "scalar") {
                issues.push(...validateScalar(schema, condition));
            } else {
                issues.push(...validateDetection(schema, condition));
            }
        }
    }

    return total;
}

/** Check a parsed definition against the schema served by the backend. */
export function validateDefinition(schema: RuleSchema, definition: Definition): ValidationIssue[] {
    const issues: ValidationIssue[] = [];

    if (definition.conditions.length === 0) {
        issues.push(issue("The rule needs at least one condition"));
        return issues;
    }

    const total = validateConditions(schema, definition.conditions, 0, issues);

    if (total > MAX_CONDITIONS) {
        issues.push(issue(`A rule holds at most ${MAX_CONDITIONS} conditions`));
    }

    return issues;
}
