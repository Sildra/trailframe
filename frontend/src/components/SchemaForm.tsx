import { useId, useMemo, useState } from "react";
import {
    Box,
    Button,
    IconButton,
    InputAdornment,
    MenuItem,
    Stack,
    TextField,
    Tooltip,
    Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import type {
    CollectionCondition,
    Condition,
    Definition,
    ElementCondition,
    MatchMode,
    Quantifier,
    ScalarCondition,
    ScalarOperator,
} from "../lib/rules";
import type {
    FieldKind,
    RuleSchema,
    SchemaCollection,
    SchemaElement,
    SchemaField,
    ValueSource,
} from "../lib/expression";
import { isPrefixUnit, operatorLabel, schemaFields } from "../lib/expression";

export interface SchemaFormProps {
    schema: RuleSchema;
    values: Record<string, string[]>;
    definition: Definition;
    onChange: (definition: Definition) => void;
}

const QUANTIFIER_LABELS: Record<Quantifier, string> = {
    any: "has any",
    none: "has none",
    one: "has one",
    all: "has all",
};

/** The parts of a field or element the value editor needs. */
interface ValueInfo {
    kind: FieldKind;
    values: ValueSource;
    key: string;
    unit?: string;
    min?: number;
    max?: number;
    step?: number;
}

function fieldInfo(field: SchemaField): ValueInfo {
    return {
        kind: field.kind,
        values: field.values,
        key: field.path,
        unit: field.unit,
        min: field.min,
        max: field.max,
        step: field.step,
    };
}

function elementInfo(element: SchemaElement): ValueInfo {
    return {
        kind: element.kind,
        values: element.values,
        key: element.values.source === "objects" ? "objects" : element.key,
        unit: element.unit,
        min: element.min,
        max: element.max,
        step: element.step,
    };
}

function suggestionsFor(info: ValueInfo, values: Record<string, string[]>): string[] {
    if (info.values.source === "static") {
        return info.values.values;
    }

    return values[info.key] ?? [];
}

function round(value: number): number {
    return Number(value.toFixed(6));
}

function firstValue(info: ValueInfo, values: Record<string, string[]>, fallback: string): string {
    return suggestionsFor(info, values)[0] ?? fallback;
}

function createCondition(field: SchemaField, values: Record<string, string[]>): ScalarCondition {
    const info = fieldInfo(field);

    if (field.kind === "bool") {
        return { type: "scalar", path: field.path, op: "eq", value: true };
    }

    if (field.kind === "number") {
        return { type: "scalar", path: field.path, op: "gte", value: field.min ?? 0 };
    }

    if (field.kind === "date") {
        return { type: "scalar", path: field.path, op: "gte", value: new Date().toISOString().slice(0, 10) };
    }

    if (field.kind === "list") {
        return { type: "scalar", path: field.path, op: "contains", value: firstValue(info, values, "") };
    }

    return { type: "scalar", path: field.path, op: "eq", value: firstValue(info, values, "") };
}

function createElementCondition(element: SchemaElement, values: Record<string, string[]>): ElementCondition {
    const info = elementInfo(element);

    if (element.kind === "bool") {
        return { type: "element", key: element.key, op: "eq", value: true };
    }

    if (element.kind === "number") {
        return { type: "element", key: element.key, op: "gte", value: element.min ?? 0 };
    }

    if (element.kind === "date") {
        return { type: "element", key: element.key, op: "gte", value: new Date().toISOString().slice(0, 10) };
    }

    if (element.kind === "list") {
        return { type: "element", key: element.key, op: "contains", value: firstValue(info, values, "") };
    }

    return { type: "element", key: element.key, op: "eq", value: firstValue(info, values, "") };
}

function createCollection(collection: SchemaCollection, values: Record<string, string[]>): CollectionCondition {
    const element = collection.elements[0];

    return {
        type: "collection",
        path: collection.path,
        quantifier: "any",
        condition: element
            ? createElementCondition(element, values)
            : { type: "element", key: "", op: "eq", value: "" },
    };
}

function ValueEditor({
    info,
    suggestions,
    value,
    onChange,
}: {
    info: ValueInfo;
    suggestions: string[];
    value: ScalarCondition["value"];
    onChange: (value: ScalarCondition["value"]) => void;
}) {
    const listId = useId();

    if (info.kind === "bool") {
        return (
            <TextField select size="small" value={String(value)} onChange={(event) => onChange(event.target.value === "true")} sx={{ minWidth: 110 }}>
                <MenuItem value="true">true</MenuItem>
                <MenuItem value="false">false</MenuItem>
            </TextField>
        );
    }

    if (info.kind === "number") {
        // `%` values are stored as 0–1 fractions; the editor shows 0–100.
        const percent = info.unit === "%";
        const factor = percent ? 100 : 1;
        const number = typeof value === "number" ? value : 0;
        const unit = info.unit;
        const adornment = unit ? <InputAdornment position={isPrefixUnit(unit) ? "start" : "end"}>{unit}</InputAdornment> : undefined;

        return (
            <TextField
                size="small"
                type="number"
                value={round(number * factor)}
                onChange={(event) => onChange(Number(event.target.value) / factor)}
                slotProps={{
                    htmlInput: {
                        min: info.min !== undefined ? info.min * factor : undefined,
                        max: info.max !== undefined ? info.max * factor : undefined,
                        step: info.step !== undefined ? info.step * factor : "any",
                    },
                    input: adornment
                        ? isPrefixUnit(unit ?? "")
                            ? { startAdornment: adornment }
                            : { endAdornment: adornment }
                        : undefined,
                }}
                sx={{ width: 140 }}
            />
        );
    }

    if (info.kind === "date") {
        return (
            <TextField
                size="small"
                type="date"
                value={typeof value === "string" ? value : ""}
                onChange={(event) => onChange(event.target.value)}
                slotProps={{ inputLabel: { shrink: true } }}
                sx={{ width: 170 }}
            />
        );
    }

    if (info.kind === "enum") {
        return (
            <TextField select size="small" value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} sx={{ minWidth: 150 }}>
                {suggestions.map((option) => (
                    <MenuItem key={option} value={option}>
                        {option}
                    </MenuItem>
                ))}
            </TextField>
        );
    }

    if (Array.isArray(value)) {
        return (
            <TextField
                size="small"
                value={value.join(", ")}
                onChange={(event) => onChange(event.target.value.split(",").map((item) => item.trim()).filter(Boolean))}
                placeholder="one, two"
                sx={{ minWidth: 200 }}
            />
        );
    }

    return (
        <>
            <TextField
                size="small"
                value={typeof value === "string" ? value : String(value ?? "")}
                onChange={(event) => onChange(event.target.value)}
                slotProps={{ htmlInput: { list: listId } }}
                sx={{ minWidth: 180 }}
            />
            <datalist id={listId}>
                {suggestions.map((option) => (
                    <option key={option} value={option} />
                ))}
            </datalist>
        </>
    );
}

function ScalarRow({
    schema,
    values,
    condition,
    onChange,
    onRemove,
}: {
    schema: RuleSchema;
    values: Record<string, string[]>;
    condition: ScalarCondition;
    onChange: (condition: ScalarCondition) => void;
    onRemove: () => void;
}) {
    const fields = schemaFields(schema);
    const field = fields.find((item) => item.path === condition.path);
    const options = (field?.operators ?? ["eq"]) as ScalarOperator[];

    return (
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", py: 0.75 }}>
            <TextField
                select
                size="small"
                value={condition.path}
                onChange={(event) => {
                    const next = fields.find((item) => item.path === event.target.value);

                    if (next) {
                        onChange(createCondition(next, values));
                    }
                }}
                sx={{ minWidth: 190 }}
            >
                {schema.groups.map((group) => [
                    <MenuItem key={`group-${group.name}`} disabled value={`group-${group.name}`}>
                        <Typography variant="caption" color="text.secondary">
                            {group.label}
                        </Typography>
                    </MenuItem>,
                    ...group.fields.map((item) => (
                        <MenuItem key={item.path} value={item.path}>
                            {item.label}
                        </MenuItem>
                    )),
                ])}
            </TextField>

            <TextField
                select
                size="small"
                value={condition.op}
                onChange={(event) => {
                    const op = event.target.value as ScalarOperator;
                    const value = op === "in" ? ([] as string[]) : op === "contains" || op === "not_contains" ? "" : condition.value;

                    onChange({ ...condition, op, value });
                }}
                sx={{ minWidth: 130 }}
            >
                {options.map((op) => (
                    <MenuItem key={op} value={op}>
                        {operatorLabel(schema, op)}
                    </MenuItem>
                ))}
            </TextField>

            {field && (
                <ValueEditor
                    info={fieldInfo(field)}
                    suggestions={suggestionsFor(fieldInfo(field), values)}
                    value={condition.value}
                    onChange={(value) => onChange({ ...condition, value })}
                />
            )}

            <Box sx={{ flex: 1 }} />
            <Tooltip title="Remove this condition">
                <IconButton size="small" color="error" aria-label="Remove condition" onClick={onRemove}>
                    <DeleteIcon fontSize="small" />
                </IconButton>
            </Tooltip>
        </Stack>
    );
}

function ElementRow({
    schema,
    values,
    collection,
    condition,
    onChange,
    onRemove,
}: {
    schema: RuleSchema;
    values: Record<string, string[]>;
    collection: SchemaCollection;
    condition: ElementCondition;
    onChange: (condition: ElementCondition) => void;
    onRemove: () => void;
}) {
    const element = collection.elements.find((item) => item.key === condition.key);
    const options = (element?.operators ?? ["eq"]) as ScalarOperator[];

    return (
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", py: 0.5 }}>
            <TextField
                select
                size="small"
                value={condition.key}
                onChange={(event) => {
                    const next = collection.elements.find((item) => item.key === event.target.value);

                    if (next) {
                        onChange(createElementCondition(next, values));
                    }
                }}
                sx={{ minWidth: 150 }}
            >
                {collection.elements.map((item) => (
                    <MenuItem key={item.key} value={item.key}>
                        {item.label}
                    </MenuItem>
                ))}
            </TextField>

            <TextField
                select
                size="small"
                value={condition.op}
                onChange={(event) => {
                    const op = event.target.value as ScalarOperator;
                    const value = op === "in" ? ([] as string[]) : op === "contains" || op === "not_contains" ? "" : condition.value;

                    onChange({ ...condition, op, value });
                }}
                sx={{ minWidth: 130 }}
            >
                {options.map((op) => (
                    <MenuItem key={op} value={op}>
                        {operatorLabel(schema, op)}
                    </MenuItem>
                ))}
            </TextField>

            {element && (
                <ValueEditor
                    info={elementInfo(element)}
                    suggestions={suggestionsFor(elementInfo(element), values)}
                    value={condition.value}
                    onChange={(value) => onChange({ ...condition, value })}
                />
            )}

            <Box sx={{ flex: 1 }} />
            <Tooltip title="Remove this key">
                <IconButton size="small" color="error" aria-label="Remove key" onClick={onRemove}>
                    <DeleteIcon fontSize="small" />
                </IconButton>
            </Tooltip>
        </Stack>
    );
}

function CollectionRow({
    schema,
    values,
    condition,
    onChange,
    onRemove,
}: {
    schema: RuleSchema;
    values: Record<string, string[]>;
    condition: CollectionCondition;
    onChange: (condition: CollectionCondition) => void;
    onRemove: () => void;
}) {
    const collection = schema.collections.find((item) => item.path === condition.path);

    if (!collection) {
        return (
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", py: 0.75 }}>
                <Typography variant="body2" color="error.main" sx={{ fontFamily: "monospace" }}>
                    Unknown collection {condition.path}
                </Typography>
                <Box sx={{ flex: 1 }} />
                <IconButton size="small" color="error" aria-label="Remove collection" onClick={onRemove}>
                    <DeleteIcon fontSize="small" />
                </IconButton>
            </Stack>
        );
    }

    const inner = condition.condition;
    const group = inner.type === "group" ? inner : null;
    const rows = group ? group.conditions : [inner];

    const replaceRow = (index: number, next: Condition) => {
        if (group) {
            onChange({
                ...condition,
                condition: { ...group, conditions: group.conditions.map((item, position) => (position === index ? next : item)) },
            });
            return;
        }

        onChange({ ...condition, condition: next });
    };

    const removeRow = (index: number) => {
        if (!group) {
            return;
        }

        const rest = group.conditions.filter((_item, position) => position !== index);
        onChange({ ...condition, condition: rest.length === 1 ? rest[0] : { ...group, conditions: rest } });
    };

    const addRow = () => {
        const element = collection.elements[0];

        if (!element) {
            return;
        }

        const created = createElementCondition(element, values);

        if (group) {
            onChange({ ...condition, condition: { ...group, conditions: [...group.conditions, created] } });
            return;
        }

        onChange({ ...condition, condition: { type: "group", match: "all", conditions: [inner, created] } });
    };

    return (
        <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1, my: 0.75 }}>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                <Typography variant="body2" sx={{ fontFamily: "monospace", fontWeight: 600 }}>
                    {collection.path}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                    {collection.description}
                </Typography>
                <Box sx={{ flex: 1 }} />
                <TextField
                    select
                    size="small"
                    value={condition.quantifier}
                    onChange={(event) => onChange({ ...condition, quantifier: event.target.value as Quantifier })}
                    sx={{ width: 130 }}
                >
                    {(Object.keys(QUANTIFIER_LABELS) as Quantifier[]).map((quantifier) => (
                        <MenuItem key={quantifier} value={quantifier}>
                            {QUANTIFIER_LABELS[quantifier]}
                        </MenuItem>
                    ))}
                </TextField>
                <Tooltip title="Remove this filter">
                    <IconButton size="small" color="error" aria-label="Remove collection" onClick={onRemove}>
                        <DeleteIcon fontSize="small" />
                    </IconButton>
                </Tooltip>
            </Stack>

            <Stack spacing={0.5} sx={{ mt: 1 }}>
                {group && group.conditions.length > 1 && (
                    <TextField
                        select
                        size="small"
                        value={group.match}
                        onChange={(event) => onChange({ ...condition, condition: { ...group, match: event.target.value as MatchMode } })}
                        sx={{ width: 140 }}
                    >
                        <MenuItem value="all">Match all keys</MenuItem>
                        <MenuItem value="any">Match any key</MenuItem>
                    </TextField>
                )}

                {rows.map((row, index) => {
                    if (row.type === "element") {
                        return (
                            <ElementRow
                                key={`element-${index}`}
                                schema={schema}
                                values={values}
                                collection={collection}
                                condition={row}
                                onChange={(next) => replaceRow(index, next)}
                                onRemove={() => removeRow(index)}
                            />
                        );
                    }

                    return (
                        <Stack key={`nested-${index}`} direction="row" spacing={1} sx={{ alignItems: "center", py: 0.5 }}>
                            <Typography variant="body2" color="text.secondary" sx={{ fontFamily: "monospace" }}>
                                (nested group · match {row.type === "group" ? row.match : row.type} · {row.type === "group" ? row.conditions.length : 0} keys)
                            </Typography>
                            <Box sx={{ flex: 1 }} />
                            <IconButton size="small" color="error" aria-label="Remove nested group" onClick={() => removeRow(index)}>
                                <DeleteIcon fontSize="small" />
                            </IconButton>
                        </Stack>
                    );
                })}

                <Box>
                    <Button size="small" startIcon={<AddIcon />} onClick={addRow} disabled={collection.elements.length === 0}>
                        Add key
                    </Button>
                </Box>
            </Stack>
        </Box>
    );
}

/** The generated schema form: every row is built from the served descriptor. */
export default function SchemaForm({ schema, values, definition, onChange }: SchemaFormProps) {
    const [pending, setPending] = useState(schema.groups[0]?.fields[0]?.path ?? schema.collections[0]?.path ?? "");
    const fields = useMemo(() => schemaFields(schema), [schema]);
    const chosenField = fields.find((field) => field.path === pending);
    const chosenCollection = schema.collections.find((collection) => collection.path === pending);
    const chosen = chosenField ?? chosenCollection;
    const description = chosenField?.description ?? chosenCollection?.description ?? "";

    const replace = (index: number, condition: Condition) => {
        onChange({
            ...definition,
            conditions: definition.conditions.map((item, position) => (position === index ? condition : item)),
        });
    };

    const remove = (index: number) => {
        onChange({ ...definition, conditions: definition.conditions.filter((_item, position) => position !== index) });
    };

    return (
        <Stack spacing={1.5}>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <Typography variant="subtitle2">Conditions</Typography>
                <TextField
                    select
                    size="small"
                    value={definition.match}
                    onChange={(event) => onChange({ ...definition, match: event.target.value as MatchMode })}
                    sx={{ width: 130 }}
                >
                    <MenuItem value="all">Match all</MenuItem>
                    <MenuItem value="any">Match any</MenuItem>
                </TextField>
                <Box sx={{ flex: 1 }} />
            </Stack>

            {definition.conditions.length === 0 && (
                <Typography variant="body2" color="text.secondary">
                    Add a condition, or write the expression above.
                </Typography>
            )}

            {definition.conditions.map((condition, index) => {
                if (condition.type === "scalar") {
                    return (
                        <ScalarRow
                            key={`scalar-${index}`}
                            schema={schema}
                            values={values}
                            condition={condition}
                            onChange={(next) => replace(index, next)}
                            onRemove={() => remove(index)}
                        />
                    );
                }

                if (condition.type === "collection") {
                    return (
                        <CollectionRow
                            key={`collection-${index}`}
                            schema={schema}
                            values={values}
                            condition={condition}
                            onChange={(next) => replace(index, next)}
                            onRemove={() => remove(index)}
                        />
                    );
                }

                if (condition.type !== "group") {
                    return null;
                }

                return (
                    <Stack key={`group-${index}`} direction="row" spacing={1} sx={{ alignItems: "center", py: 0.75 }}>
                        <Typography variant="body2" color="text.secondary" sx={{ fontFamily: "monospace" }}>
                            (group · match {condition.match} · {condition.conditions.length} conditions)
                        </Typography>
                        <Box sx={{ flex: 1 }} />
                        <IconButton size="small" color="error" aria-label="Remove group" onClick={() => remove(index)}>
                            <DeleteIcon fontSize="small" />
                        </IconButton>
                    </Stack>
                );
            })}

            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", pt: 0.5 }}>
                <TextField
                    select
                    size="small"
                    value={pending}
                    onChange={(event) => setPending(event.target.value)}
                    sx={{ minWidth: 220 }}
                >
                    {schema.groups.map((group) => [
                        <MenuItem key={`add-group-${group.name}`} disabled value={`add-${group.name}`}>
                            <Typography variant="caption" color="text.secondary">
                                {group.label}
                            </Typography>
                        </MenuItem>,
                        ...group.fields.map((field) => (
                            <MenuItem key={field.path} value={field.path}>
                                {field.label}
                            </MenuItem>
                        )),
                    ])}
                    {schema.collections.length > 0 && (
                        <MenuItem disabled value="add-collections">
                            <Typography variant="caption" color="text.secondary">
                                Collections
                            </Typography>
                        </MenuItem>
                    )}
                    {schema.collections.map((collection) => (
                        <MenuItem key={collection.path} value={collection.path}>
                            {collection.label}
                        </MenuItem>
                    ))}
                </TextField>
                <Button
                    size="small"
                    variant="outlined"
                    startIcon={<AddIcon />}
                    disabled={!chosen}
                    onClick={() => {
                        if (chosenField) {
                            onChange({ ...definition, conditions: [...definition.conditions, createCondition(chosenField, values)] });
                            return;
                        }

                        if (chosenCollection) {
                            onChange({ ...definition, conditions: [...definition.conditions, createCollection(chosenCollection, values)] });
                        }
                    }}
                >
                    Add condition
                </Button>
                <Typography variant="caption" color="text.secondary">
                    {description}
                </Typography>
            </Stack>
        </Stack>
    );
}
