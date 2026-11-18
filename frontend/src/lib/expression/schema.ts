import type { Condition, Definition, Quantifier, ScalarOperator } from "../rules";

export type FieldKind = "text" | "number" | "date" | "bool" | "enum" | "list";

export interface ValueSource {
    source: "none" | "static" | "distinct" | "objects" | "tags" | "scanners";
    values: string[];
}

export interface SchemaField {
    path: string;
    group: string;
    label: string;
    description: string;
    kind: FieldKind;
    operators: ScalarOperator[];
    computed: boolean;
    values: ValueSource;
    min?: number;
    max?: number;
    step?: number;
    unit?: string;
}

/** One filterable key of a collection element. */
export interface SchemaElement {
    key: string;
    label: string;
    description: string;
    kind: FieldKind;
    operators: ScalarOperator[];
    values: ValueSource;
    min?: number;
    max?: number;
    step?: number;
    unit?: string;
}

export interface SchemaCollection {
    path: string;
    group: string;
    label: string;
    description: string;
    quantifiers: Quantifier[];
    elements: SchemaElement[];
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

export interface SchemaQuantifier {
    name: Quantifier;
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
    quantifiers: SchemaQuantifier[];
    collections: SchemaCollection[];
    groups: SchemaGroup[];
}

export interface ValidationIssue {
    message: string;
}

export const MAX_CONDITIONS = 20;
export const MAX_GROUP_DEPTH = 4;

/** Every scalar field of the schema, flattened. */
export function schemaFields(schema: RuleSchema): SchemaField[] {
    return schema.groups.flatMap((group) => group.fields);
}

/** The scalar field at `path`, when it exists. */
export function fieldFor(schema: RuleSchema, path: string): SchemaField | undefined {
    return schemaFields(schema).find((field) => field.path === path);
}

/** The collection at `path`, when it exists. */
export function collectionFor(schema: RuleSchema, path: string): SchemaCollection | undefined {
    return schema.collections.find((collection) => collection.path === path);
}

/** The element key of a collection, when it exists. */
export function elementFor(collection: SchemaCollection, key: string): SchemaElement | undefined {
    return collection.elements.find((element) => element.key === key);
}

/** The operator label the editor shows for a field. */
export function operatorLabel(schema: RuleSchema, name: string): string {
    return schema.grammar.operators[name]?.label ?? name;
}

/** The operator token the expression uses. */
export function operatorToken(schema: RuleSchema, name: string): string {
    return schema.grammar.operators[name]?.token ?? name;
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

function validateOperand(
    label: string,
    kind: FieldKind,
    op: ScalarOperator,
    value: unknown,
    low?: number,
    high?: number,
): ValidationIssue[] {
    if (op === "in") {
        if (!Array.isArray(value) || value.length === 0) {
            return [issue("'in' needs a non-empty list of values")];
        }

        if (kind === "number" && value.some((item) => !isNumber(Number(item)))) {
            return [issue(`'${label}' needs a list of numbers`)];
        }

        return [];
    }

    if (kind === "number") {
        if (!isNumber(value)) {
            return [issue(`'${label}' needs a number`)];
        }

        if (low !== undefined && high !== undefined && (value < low || value > high)) {
            return [issue(`'${label}' must be between ${low} and ${high}`)];
        }
    }

    if (kind === "date" && !isDate(value)) {
        return [issue(`'${label}' needs a YYYY-MM-DD date`)];
    }

    if (kind === "bool" && typeof value !== "boolean") {
        return [issue(`'${label}' needs true or false`)];
    }

    if ((kind === "text" || kind === "enum" || kind === "list") && typeof value !== "string") {
        return [issue(`'${label}' needs text`)];
    }

    return [];
}

function validateScalar(schema: RuleSchema, condition: Extract<Condition, { type: "scalar" }>): ValidationIssue[] {
    const field = fieldFor(schema, condition.path);

    if (!field) {
        return [issue(`Unknown field '${condition.path}'`)];
    }

    if (!(field.operators as string[]).includes(condition.op)) {
        return [issue(`'${condition.op}' cannot be used on '${condition.path}'`)];
    }

    return validateOperand(condition.path, field.kind, condition.op, condition.value);
}

function validateElement(
    collection: SchemaCollection,
    condition: Extract<Condition, { type: "element" }>,
): ValidationIssue[] {
    const element = elementFor(collection, condition.key);

    if (!element) {
        return [issue(`Unknown ${collection.path} key '${condition.key}'`)];
    }

    if (!(element.operators as string[]).includes(condition.op)) {
        return [issue(`'${condition.op}' cannot be used on '${collection.path}.${condition.key}'`)];
    }

    return validateOperand(condition.key, element.kind, condition.op, condition.value, element.min, element.max);
}

function validateConditions(
    schema: RuleSchema,
    conditions: Condition[],
    depth: number,
    scope: "root" | "element",
    issues: ValidationIssue[],
    collection?: SchemaCollection,
): number {
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

            total += validateConditions(schema, condition.conditions, depth + 1, scope, issues, collection);
            continue;
        }

        if (condition.type === "collection") {
            total += 1;

            if (scope !== "root") {
                issues.push(issue("Collections cannot be nested"));
                continue;
            }

            const spec = collectionFor(schema, condition.path);

            if (!spec) {
                issues.push(issue(`Unknown collection '${condition.path}'`));
                continue;
            }

            if (!spec.quantifiers.includes(condition.quantifier)) {
                issues.push(issue(`Unknown quantifier '${condition.quantifier}'`));
            }

            total += validateConditions(schema, [condition.condition], depth + 1, "element", issues, spec) - 1;
            continue;
        }

        if (condition.type === "element") {
            total += 1;

            if (scope !== "element" || !collection) {
                issues.push(issue("Element conditions only belong inside a collection filter"));
                continue;
            }

            issues.push(...validateElement(collection, condition));
            continue;
        }

        total += 1;

        if (scope !== "root") {
            issues.push(issue("A collection filter compares element keys, not photo fields"));
            continue;
        }

        issues.push(...validateScalar(schema, condition));
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

    const total = validateConditions(schema, definition.conditions, 0, "root", issues);

    if (total > MAX_CONDITIONS) {
        issues.push(issue(`A rule holds at most ${MAX_CONDITIONS} conditions`));
    }

    return issues;
}
