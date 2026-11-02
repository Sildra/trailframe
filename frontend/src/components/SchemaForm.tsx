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
    Condition,
    Definition,
    DetectionCondition,
    MatchMode,
    MetricConstraint,
    NumericOperator,
    ScalarCondition,
    ScalarOperator,
} from "../lib/rules";
import type { RuleSchema, SchemaField, SchemaMetric } from "../lib/expression";
import { isPrefixUnit, operatorLabel } from "../lib/expression";

export interface SchemaFormProps {
    schema: RuleSchema;
    values: Record<string, string[]>;
    definition: Definition;
    onChange: (definition: Definition) => void;
}

const NUMERIC_OPERATORS: NumericOperator[] = ["eq", "neq", "gt", "gte", "lt", "lte"];

function createCondition(field: SchemaField, values: Record<string, string[]>): Condition {
    if (field.kind === "detection") {
        return { type: "detection", label: "", op: "present", metrics: [] };
    }

    if (field.kind === "bool") {
        return { type: "scalar", path: field.path, op: "eq", value: true };
    }

    if (field.kind === "number") {
        return { type: "scalar", path: field.path, op: "gte", value: field.min ?? 0 };
    }

    if (field.kind === "date") {
        return { type: "scalar", path: field.path, op: "gte", value: new Date().toISOString().slice(0, 10) };
    }

    if (field.kind === "enum") {
        const options = field.values.values.length > 0 ? field.values.values : (values[field.path] ?? []);

        return { type: "scalar", path: field.path, op: "eq", value: options[0] ?? "" };
    }

    if (field.kind === "list") {
        return { type: "scalar", path: field.path, op: "contains", value: values[field.path]?.[0] ?? "" };
    }

    return { type: "scalar", path: field.path, op: "eq", value: values[field.path]?.[0] ?? "" };
}

function suggestionsFor(field: SchemaField | undefined, values: Record<string, string[]>): string[] {
    if (!field) {
        return [];
    }

    if (field.values.source === "static") {
        return field.values.values;
    }

    return values[field.path] ?? [];
}

function ValueEditor({
    field,
    values,
    value,
    onChange,
}: {
    field: SchemaField;
    values: Record<string, string[]>;
    value: ScalarCondition["value"];
    onChange: (value: ScalarCondition["value"]) => void;
}) {
    const listId = useId();
    const suggestions = suggestionsFor(field, values);

    if (field.kind === "bool") {
        return (
            <TextField select size="small" value={String(value)} onChange={(event) => onChange(event.target.value === "true")} sx={{ minWidth: 110 }}>
                <MenuItem value="true">true</MenuItem>
                <MenuItem value="false">false</MenuItem>
            </TextField>
        );
    }

    if (field.kind === "number") {
        const unit = field.unit;
        const adornment = unit ? <InputAdornment position={isPrefixUnit(unit) ? "start" : "end"}>{unit}</InputAdornment> : undefined;

        return (
            <TextField
                size="small"
                type="number"
                value={typeof value === "number" ? value : 0}
                onChange={(event) => onChange(Number(event.target.value))}
                slotProps={{
                    htmlInput: { min: field.min, max: field.max, step: field.step ?? "any" },
                    input: adornment
                        ? isPrefixUnit(unit)
                            ? { startAdornment: adornment }
                            : { endAdornment: adornment }
                        : undefined,
                }}
                sx={{ width: 140 }}
            />
        );
    }

    if (field.kind === "date") {
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

    if (field.kind === "enum") {
        const options = suggestions.length > 0 ? suggestions : field.values.values;

        return (
            <TextField select size="small" value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} sx={{ minWidth: 150 }}>
                {options.map((option) => (
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
    const fields = schema.groups.flatMap((group) => group.fields).filter((field) => field.kind !== "detection");
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
                        const created = createCondition(next, values);

                        if (created.type === "scalar") {
                            onChange(created);
                        }
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
                    ...group.fields
                        .filter((item) => item.kind !== "detection")
                        .map((item) => (
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
                <ValueEditor field={field} values={values} value={condition.value} onChange={(value) => onChange({ ...condition, value })} />
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

function DetectionRow({
    schema,
    values,
    condition,
    onChange,
    onRemove,
}: {
    schema: RuleSchema;
    values: Record<string, string[]>;
    condition: DetectionCondition;
    onChange: (condition: DetectionCondition) => void;
    onRemove: () => void;
}) {
    const labels = values[schema.detection.path] ?? schema.detection.label_values.values;
    const listId = useId();
    const metrics: SchemaMetric[] = schema.detection.metrics;

    const updateMetric = (index: number, metric: MetricConstraint) => {
        const next = condition.metrics.map((item, position) => (position === index ? metric : item));
        onChange({ ...condition, metrics: next });
    };

    return (
        <Box sx={{ py: 0.75 }}>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                <Typography variant="body2" sx={{ fontFamily: "monospace", minWidth: 62 }}>
                    objects
                </Typography>

                <TextField
                    select
                    size="small"
                    value={condition.op}
                    onChange={(event) => onChange({ ...condition, op: event.target.value as "present" | "absent" })}
                    sx={{ minWidth: 110 }}
                >
                    <MenuItem value="present">has</MenuItem>
                    <MenuItem value="absent">has no</MenuItem>
                </TextField>

                <TextField
                    size="small"
                    value={condition.label}
                    onChange={(event) => onChange({ ...condition, label: event.target.value })}
                    placeholder="label"
                    slotProps={{ htmlInput: { list: listId } }}
                    sx={{ minWidth: 160 }}
                />
                <datalist id={listId}>
                    {labels.map((label) => (
                        <option key={label} value={label} />
                    ))}
                </datalist>

                <Button
                    size="small"
                    startIcon={<AddIcon />}
                    disabled={condition.op === "absent"}
                    onClick={() => {
                        const first = metrics[0];

                        if (first) {
                            onChange({ ...condition, metrics: [...condition.metrics, { name: first.name, op: "gte", value: (first.min + first.max) / 2 }] });
                        }
                    }}
                >
                    Metric
                </Button>

                <Box sx={{ flex: 1 }} />
                <Tooltip title="Remove this condition">
                    <IconButton size="small" color="error" aria-label="Remove condition" onClick={onRemove}>
                        <DeleteIcon fontSize="small" />
                    </IconButton>
                </Tooltip>
            </Stack>

            {condition.op === "present" &&
                condition.metrics.map((metric, index) => {
                    const spec = metrics.find((item) => item.name === metric.name);
                    const unit = spec?.unit;
                    const adornment = unit ? (
                        <InputAdornment position={isPrefixUnit(unit) ? "start" : "end"}>{unit}</InputAdornment>
                    ) : undefined;

                    return (
                        <Stack key={`metric-${index}`} direction="row" spacing={1} sx={{ alignItems: "center", ml: 9, mt: 0.5 }}>
                            <TextField
                                select
                                size="small"
                                value={metric.name}
                                onChange={(event) => updateMetric(index, { ...metric, name: event.target.value })}
                                sx={{ minWidth: 130 }}
                            >
                                {metrics.map((item) => (
                                    <MenuItem key={item.name} value={item.name}>
                                        {item.label}
                                    </MenuItem>
                                ))}
                            </TextField>
                            <TextField
                                select
                                size="small"
                                value={metric.op}
                                onChange={(event) => updateMetric(index, { ...metric, op: event.target.value as NumericOperator })}
                                sx={{ minWidth: 110 }}
                            >
                                {NUMERIC_OPERATORS.map((op) => (
                                    <MenuItem key={op} value={op}>
                                        {operatorLabel(schema, op)}
                                    </MenuItem>
                                ))}
                            </TextField>
                            <TextField
                                size="small"
                                type="number"
                                value={metric.value}
                                onChange={(event) => updateMetric(index, { ...metric, value: Number(event.target.value) })}
                                slotProps={{
                                    htmlInput: { min: spec?.min, max: spec?.max, step: spec?.step ?? "any" },
                                    input: adornment
                                        ? isPrefixUnit(unit ?? "")
                                            ? { startAdornment: adornment }
                                            : { endAdornment: adornment }
                                        : undefined,
                                }}
                                sx={{ width: 130 }}
                            />
                            <IconButton
                                size="small"
                                aria-label="Remove metric"
                                onClick={() => onChange({ ...condition, metrics: condition.metrics.filter((_item, position) => position !== index) })}
                            >
                                <DeleteIcon fontSize="small" />
                            </IconButton>
                        </Stack>
                    );
                })}
        </Box>
    );
}

/** The generated schema form: every row is built from the served descriptor. */
export default function SchemaForm({ schema, values, definition, onChange }: SchemaFormProps) {
    const [pending, setPending] = useState(schema.groups[0]?.fields[0]?.path ?? "objects");
    const fields = useMemo(() => schema.groups.flatMap((group) => group.fields), [schema]);
    const chosen = fields.find((field) => field.path === pending) ?? fields[0];

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

                if (condition.type === "detection") {
                    return (
                        <DetectionRow
                            key={`detection-${index}`}
                            schema={schema}
                            values={values}
                            condition={condition}
                            onChange={(next) => replace(index, next)}
                            onRemove={() => remove(index)}
                        />
                    );
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
                </TextField>
                <Button
                    size="small"
                    variant="outlined"
                    startIcon={<AddIcon />}
                    disabled={!chosen}
                    onClick={() => {
                        if (!chosen) {
                            return;
                        }

                        onChange({ ...definition, conditions: [...definition.conditions, createCondition(chosen, values)] });
                    }}
                >
                    Add condition
                </Button>
                <Typography variant="caption" color="text.secondary">
                    {chosen?.description}
                </Typography>
            </Stack>
        </Stack>
    );
}
