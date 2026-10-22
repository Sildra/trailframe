import { useMemo } from "react";
import {
    Box,
    Button,
    Chip,
    Divider,
    FormControl,
    IconButton,
    InputLabel,
    MenuItem,
    Select,
    Stack,
    TextField,
    Tooltip,
    Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import type { RuleCondition, RuleConstraint, RuleDraft, RuleOperator, TagRuleField } from "../lib/rules";
import { EMPTY_CONDITION, fieldOperators, findField } from "../lib/rules";

export interface RuleBuilderProps {
    draft: RuleDraft;
    fields: TagRuleField[];
    onChange: (draft: RuleDraft) => void;
    /** The tag paths offered by the picker. */
    tagOptions: string[];
}

const CONSTRAINT_OPERATORS = [
    { op: "gte", label: "is at least" },
    { op: "gt", label: "is more than" },
    { op: "lte", label: "is at most" },
    { op: "lt", label: "is less than" },
    { op: "eq", label: "equals" },
];

function updateCondition(draft: RuleDraft, index: number, changes: Partial<RuleCondition>): RuleDraft {
    return {
        ...draft,
        conditions: draft.conditions.map((condition, position) =>
            position === index ? { ...condition, ...changes } : condition,
        ),
    };
}

function ConstraintRow({
    metric,
    constraint,
    onChange,
    onRemove,
}: {
    metric: string;
    constraint: RuleConstraint;
    onChange: (op: RuleOperator, value: string) => void;
    onRemove: () => void;
}) {
    return (
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <Typography variant="caption" sx={{ width: 76, flexShrink: 0 }}>
                {metric}
            </Typography>
            <FormControl size="small" sx={{ minWidth: 130 }}>
                <Select
                    value={constraint.op}
                    onChange={(event) => onChange(event.target.value, constraint.value)}
                    slotProps={{ input: { "aria-label": `${metric} comparison` } }}
                >
                    {CONSTRAINT_OPERATORS.map((operator) => (
                        <MenuItem key={operator.op} value={operator.op}>
                            {operator.label}
                        </MenuItem>
                    ))}
                </Select>
            </FormControl>
            <TextField
                size="small"
                value={constraint.value}
                onChange={(event) => onChange(constraint.op, event.target.value)}
                placeholder="0.8"
                slotProps={{ htmlInput: { "aria-label": `${metric} value` } }}
                sx={{ width: 110 }}
            />
            <Tooltip title="Remove this constraint">
                <IconButton size="small" aria-label="Remove constraint" onClick={onRemove}>
                    <DeleteIcon fontSize="small" />
                </IconButton>
            </Tooltip>
        </Stack>
    );
}

function ConditionRow({
    condition,
    index,
    fields,
    onChange,
    onRemove,
    canRemove,
}: {
    condition: RuleCondition;
    index: number;
    fields: TagRuleField[];
    onChange: (changes: Partial<RuleCondition>) => void;
    onRemove: () => void;
    canRemove: boolean;
}) {
    const field = findField(fields, condition.field);
    const isObject = condition.field === "objects";
    const operators = fieldOperators(field);
    const suggestions = field?.suggestions ?? [];

    const setField = (name: string) => {
        const next = findField(fields, name);
        const first = next?.operators?.[0]?.op ?? "eq";

        onChange({ field: name, operator: first as RuleCondition["operator"], value: "", constraints: {} });
    };

    return (
        <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5 }}>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", gap: 1 }}>
                <FormControl size="small" sx={{ minWidth: 200 }}>
                    <InputLabel id={`rule-field-label-${index}`}>Metadata</InputLabel>
                    <Select
                        labelId={`rule-field-label-${index}`}
                        id={`rule-field-${index}`}
                        label="Metadata"
                        value={condition.field}
                        onChange={(event) => setField(event.target.value)}
                    >
                        {fields.map((entry) => (
                            <MenuItem key={entry.field} value={entry.field}>
                                {entry.group} › {entry.label}
                            </MenuItem>
                        ))}
                    </Select>
                </FormControl>

                {isObject ? (
                    <>
                        <TextField
                            size="small"
                            label="Detected object"
                            value={condition.match_label}
                            onChange={(event) => onChange({ match_label: event.target.value })}
                            placeholder="dog"
                            helperText="The label the detector found, in lowercase."
                            sx={{ width: 220 }}
                            slotProps={{ htmlInput: { list: `object-labels-${index}` } }}
                        />
                        <datalist id={`object-labels-${index}`}>
                            {suggestions.map((suggestion) => (
                                <option key={suggestion} value={suggestion} />
                            ))}
                        </datalist>

                        <FormControl size="small" sx={{ minWidth: 140 }}>
                            <InputLabel id={`rule-object-op-label-${index}`}>Is</InputLabel>
                            <Select
                                labelId={`rule-object-op-label-${index}`}
                                id={`rule-object-op-${index}`}
                                label="Is"
                                value={condition.operator}
                                onChange={(event) => onChange({ operator: event.target.value as RuleCondition["operator"] })}
                            >
                                {operators.map((operator) => (
                                    <MenuItem key={operator.op} value={operator.op}>
                                        {operator.label}
                                    </MenuItem>
                                ))}
                            </Select>
                        </FormControl>
                    </>
                ) : (
                    <>
                        <FormControl size="small" sx={{ minWidth: 150 }}>
                            <InputLabel id={`rule-op-label-${index}`}>Comparison</InputLabel>
                            <Select
                                labelId={`rule-op-label-${index}`}
                                id={`rule-op-${index}`}
                                label="Comparison"
                                value={condition.operator}
                                onChange={(event) => onChange({ operator: event.target.value as RuleCondition["operator"] })}
                            >
                                {operators.map((operator) => (
                                    <MenuItem key={operator.op} value={operator.op}>
                                        {operator.label}
                                    </MenuItem>
                                ))}
                            </Select>
                        </FormControl>
                        <TextField
                            size="small"
                            label="Value"
                            value={condition.value}
                            onChange={(event) => onChange({ value: event.target.value })}
                            sx={{ width: 200 }}
                            slotProps={{ htmlInput: { list: `field-values-${index}` } }}
                        />
                        <datalist id={`field-values-${index}`}>
                            {suggestions.map((suggestion) => (
                                <option key={suggestion} value={suggestion} />
                            ))}
                        </datalist>
                    </>
                )}

                <Box sx={{ flex: 1 }} />

                {canRemove && (
                    <Tooltip title="Remove this condition">
                        <IconButton size="small" aria-label="Remove condition" onClick={onRemove}>
                            <DeleteIcon fontSize="small" />
                        </IconButton>
                    </Tooltip>
                )}
            </Stack>

            {field && (
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                    {field.description}
                </Typography>
            )}

            {isObject && (
                <Stack spacing={1} sx={{ mt: 1.5, pl: 1 }}>
                    {(field?.metrics ?? []).map((metric) => {
                        const constraint: RuleConstraint = condition.constraints[metric] ?? { op: "gte", value: "" };

                        return (
                            <ConstraintRow
                                key={metric}
                                metric={metric}
                                constraint={constraint}
                                onChange={(op, value) =>
                                    onChange({
                                        constraints: { ...condition.constraints, [metric]: { op, value } },
                                    })
                                }                                onRemove={() => {
                                    const next = { ...condition.constraints };

                                    delete next[metric];
                                    onChange({ constraints: next });
                                }}
                            />
                        );
                    })}
                </Stack>
            )}
        </Box>
    );
}

export default function RuleBuilder({ draft, fields, onChange, tagOptions }: RuleBuilderProps) {
    const known = useMemo(() => new Set(tagOptions), [tagOptions]);

    const setTag = (path: string) => {
        const trimmed = path.trim();

        if (!trimmed || draft.tags.includes(trimmed)) {
            return;
        }

        onChange({ ...draft, tags: [...draft.tags, trimmed] });
    };

    return (
        <Stack spacing={2}>
            <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", gap: 2 }}>
                <TextField
                    label="Rule name"
                    size="small"
                    value={draft.name}
                    onChange={(event) => onChange({ ...draft, name: event.target.value })}
                    sx={{ width: 260 }}
                />
                <TextField
                    label="Priority"
                    size="small"
                    type="number"
                    value={draft.priority}
                    onChange={(event) => onChange({ ...draft, priority: Number(event.target.value) || 0 })}
                    helperText="Higher priority rules are evaluated first."
                    sx={{ width: 200 }}
                />
            </Stack>

            <TextField
                label="Description"
                size="small"
                multiline
                minRows={2}
                value={draft.description}
                onChange={(event) => onChange({ ...draft, description: event.target.value })}
            />

            <Divider />

            <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                    Conditions
                </Typography>

                <Stack spacing={1} sx={{ mb: 1 }}>
                    <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                        <Typography variant="body2" color="text.secondary">
                            Match
                        </Typography>
                        <FormControl size="small" sx={{ minWidth: 120 }}>
                            <Select
                                value={draft.operator}
                                onChange={(event) =>
                                    onChange({ ...draft, operator: event.target.value as RuleDraft["operator"] })
                                }
                                slotProps={{ input: { "aria-label": "Combine conditions" } }}
                            >
                                <MenuItem value="and">all conditions</MenuItem>
                                <MenuItem value="or">any condition</MenuItem>
                            </Select>
                        </FormControl>
                        <Typography variant="body2" color="text.secondary">
                            of the following
                        </Typography>
                    </Stack>

                    {draft.conditions.map((condition, index) => (
                        <ConditionRow
                            key={`condition-${index}`}
                            condition={condition}
                            index={index}
                            fields={fields}
                            canRemove={draft.conditions.length > 1}
                            onChange={(changes) => onChange(updateCondition(draft, index, changes))}
                            onRemove={() =>
                                onChange({
                                    ...draft,
                                    conditions: draft.conditions.filter((_, position) => position !== index),
                                })
                            }
                        />
                    ))}

                    <Box>
                        <Button
                            size="small"
                            startIcon={<AddIcon />}
                            onClick={() => onChange({ ...draft, conditions: [...draft.conditions, { ...EMPTY_CONDITION }] })}
                        >
                            Add condition
                        </Button>
                    </Box>
                </Stack>
            </Box>

            <Divider />

            <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                    Tags to assign
                </Typography>

                <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1, mb: 1 }}>
                    {draft.tags.map((tag) => (
                        <Chip
                            key={`rule-tag-${tag}`}
                            size="small"
                            label={tag}
                            onDelete={() => onChange({ ...draft, tags: draft.tags.filter((entry) => entry !== tag) })}
                        />
                    ))}
                    {draft.tags.length === 0 && (
                        <Typography variant="body2" color="text.secondary">
                            No tag yet — the rule needs at least one.
                        </Typography>
                    )}
                </Stack>

                <TextField
                    size="small"
                    label="Add a tag"
                    placeholder="Animals/Pet/Dog"
                    onKeyDown={(event) => {
                        if (event.key === "Enter") {
                            event.preventDefault();
                            const input = event.target as HTMLInputElement;

                            setTag(input.value);
                            input.value = "";
                        }
                    }}
                    helperText="Press Enter to add the tag. A tag that is not in the vocabulary yet is created when the rule runs."
                    sx={{ width: 320 }}
                    slotProps={{ htmlInput: { list: "rule-tag-options" } }}
                />
                <datalist id="rule-tag-options">
                    {[...known].sort().map((tag) => (
                        <option key={`rule-tag-option-${tag}`} value={tag} />
                    ))}
                </datalist>
            </Box>
        </Stack>
    );
}
