import { useEffect, useMemo, useState } from "react";
import {
    Box,
    Button,
    CircularProgress,
    Divider,
    FormControlLabel,
    IconButton,
    Stack,
    Switch,
    TextField,
    Tooltip,
    Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import SaveIcon from "@mui/icons-material/Save";
import UndoIcon from "@mui/icons-material/Undo";
import { api } from "../api/client";
import ExpressionEditor from "../components/ExpressionEditor";
import SchemaForm from "../components/SchemaForm";
import { useRulePreview } from "../hooks/useRulePreview";
import {
    parseExpression,
    printDefinition,
    validateDefinition,
    type ParseIssue,
    type RuleSchema,
} from "../lib/expression";
import type { Definition } from "../lib/rules";
import type { components } from "../api/generated/schema";

type Rule = components["schemas"]["RuleResponse"];

export interface RulePageProps {
    /** The tag path the rule is scoped to and assigns. */
    tagPath: string;
    /** The stored rule to edit, or null for a new one. */
    rule: Rule | null;
    /** Return to the tag's inner page. */
    onBack: () => void;
    /** Called once the rule was saved. */
    onSaved: () => void;
}

function storedDefinition(rule: Rule | null): Definition {
    return rule === null ? { version: 1, match: "all", conditions: [] } : (rule.definition as Definition);
}

function initialExpression(rule: Rule | null): string {
    return rule === null ? "" : printDefinition(storedDefinition(rule));
}

/** The detail page of one rule: expression on top, generated schema form below. */
export default function RulePage({ tagPath, rule, onBack, onSaved }: RulePageProps) {
    const stored = useMemo(() => storedDefinition(rule), [rule]);
    const initial = useMemo(() => initialExpression(rule), [rule]);
    const [schema, setSchema] = useState<RuleSchema | null>(null);
    const [values, setValues] = useState<Record<string, string[]>>({});
    const [loadError, setLoadError] = useState<string | null>(null);
    const [name, setName] = useState(rule?.name ?? "");
    const [description, setDescription] = useState(rule?.description ?? "");
    const [enabled, setEnabled] = useState(rule?.enabled ?? true);
    const [priority, setPriority] = useState(rule?.priority ?? 0);
    const [expression, setExpression] = useState(initial);
    const [composing, setComposing] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const baseline = useMemo(
        () => ({
            name: rule?.name ?? "",
            description: rule?.description ?? "",
            enabled: rule?.enabled ?? true,
            priority: rule?.priority ?? 0,
            expression: rule === null ? "" : printDefinition(stored, schema ?? undefined),
        }),
        [rule, stored, schema],
    );

    useEffect(() => {
        let cancelled = false;

        Promise.all([api.GET("/api/rules/schema"), api.GET("/api/rules/values")])
            .then(([schemaResponse, valuesResponse]) => {
                if (cancelled) {
                    return;
                }

                if (schemaResponse.error || !schemaResponse.data) {
                    setLoadError("The rule schema could not be loaded.");
                    return;
                }

                const loaded = schemaResponse.data as unknown as RuleSchema;

                setSchema(loaded);
                setValues(valuesResponse.data ?? {});
                // Legacy expressions have no units yet, so reprint them now that
                // the schema says which units each field expects.
                setExpression((current) => (rule === null || current !== initial ? current : printDefinition(stored, loaded)));
            })
            .catch(() => {
                if (!cancelled) {
                    setLoadError("The rule schema could not be loaded.");
                }
            });

        return () => {
            cancelled = true;
        };
    }, [rule, stored, initial]);

    const parsed = useMemo(() => parseExpression(expression, schema), [expression, schema]);
    const schemaIssues = useMemo(
        () => (schema && parsed.definition ? validateDefinition(schema, parsed.definition) : []),
        [schema, parsed.definition],
    );
    const valid = parsed.definition !== null && schema !== null && schemaIssues.length === 0;
    const issue: ParseIssue | null =
        parsed.issues[0] ?? (schemaIssues[0] ? { message: schemaIssues[0].message, start: expression.length, end: expression.length } : null);
    const preview = useRulePreview(tagPath, valid ? parsed.definition : null, !composing);
    const definition = parsed.definition;
    const dirty =
        name !== baseline.name ||
        description !== baseline.description ||
        enabled !== baseline.enabled ||
        priority !== baseline.priority ||
        expression !== baseline.expression;

    const revert = () => {
        setName(baseline.name);
        setDescription(baseline.description);
        setEnabled(baseline.enabled);
        setPriority(baseline.priority);
        setExpression(baseline.expression);
        setError(null);
    };

    const save = async () => {
        if (!valid || definition === null) {
            return;
        }

        setSaving(true);
        setError(null);

        const body = {
            tag: tagPath,
            name: name.trim(),
            description,
            enabled,
            priority,
            expression,
            definition,
        };

        const response =
            rule === null
                ? await api.POST("/api/rules", { body })
                : await api.PUT("/api/rules/{rule_id}", { params: { path: { rule_id: rule.id } }, body });

        setSaving(false);

        if (response.error || !response.data) {
            setError("The rule could not be saved.");
            return;
        }

        onSaved();
    };

    return (
        <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto", p: 2 }}>
            <Stack spacing={2} sx={{ maxWidth: 900, width: "100%", mx: "auto" }}>
                <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
                    <Tooltip title="Back to the tag">
                        <IconButton size="small" aria-label="Back to tag" onClick={onBack}>
                            <ArrowBackIcon fontSize="small" />
                        </IconButton>
                    </Tooltip>

                    <Box sx={{ flex: 1, minWidth: 180 }}>
                        <Typography variant="h6" sx={{ fontWeight: 600 }}>
                            {name.trim() || (rule === null ? "New rule" : "Rule")}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                            Assigns the tag <strong>{tagPath}</strong>
                        </Typography>
                    </Box>

                    <FormControlLabel
                        control={<Switch size="small" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />}
                        label="Enabled"
                    />

                    <Button size="small" startIcon={<UndoIcon />} onClick={revert} disabled={!dirty || saving}>
                        Revert
                    </Button>
                    <Button
                        size="small"
                        variant="contained"
                        startIcon={<SaveIcon />}
                        onClick={save}
                        disabled={!dirty || saving || !valid || !name.trim()}
                    >
                        Save
                    </Button>
                </Box>

                {(error || loadError) && (
                    <Typography variant="body2" color="error.main">
                        {error ?? loadError}
                    </Typography>
                )}

                <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                    <TextField
                        label="Rule name"
                        size="small"
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        required
                        sx={{ flex: 1, minWidth: 200 }}
                    />
                    <TextField
                        label="Priority"
                        size="small"
                        type="number"
                        value={priority}
                        onChange={(event) => setPriority(Number(event.target.value))}
                        sx={{ width: 130 }}
                    />
                    <TextField
                        label="Description"
                        size="small"
                        value={description}
                        onChange={(event) => setDescription(event.target.value)}
                        sx={{ flex: 2, minWidth: 220 }}
                    />
                </Stack>

                <Box>
                    <Typography variant="subtitle2" sx={{ mb: 1 }}>
                        Expression
                    </Typography>
                    <ExpressionEditor
                        value={expression}
                        onChange={(next) => {
                            setExpression(next);
                            setError(null);
                        }}
                        issue={issue}
                        onCompositionChange={setComposing}
                        schema={schema}
                        values={values}
                    />
                    <Typography variant="caption" color="text.secondary">
                        Parsed, validated and coloured in the browser; the server only receives the parsed definition.
                    </Typography>
                </Box>

                <Divider />

                {schema === null ? (
                    <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
                        <CircularProgress size={24} />
                    </Box>
                ) : (
                    <SchemaForm
                        schema={schema}
                        values={values}
                        definition={definition ?? { version: 1, match: "all", conditions: [] }}
                        onChange={(next) => {
                            setExpression(printDefinition(next, schema));
                            setError(null);
                        }}
                    />
                )}

                <Divider />

                <Box>
                    <Typography variant="subtitle2" sx={{ mb: 1 }}>
                        Expected matches
                    </Typography>

                    {!valid ? (
                        <Typography variant="body2" color="text.secondary">
                            The rule is not valid yet, so no preview is queried.
                        </Typography>
                    ) : preview.error ? (
                        <Typography variant="body2" color="error.main">
                            {preview.error}
                        </Typography>
                    ) : preview.loading || preview.result === null ? (
                        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                            <CircularProgress size={16} />
                            <Typography variant="body2" color="text.secondary">
                                Scanning the library…
                            </Typography>
                        </Box>
                    ) : (
                        <>
                            <Typography variant="body2">
                                {preview.result.count} matching photo{preview.result.count === 1 ? "" : "s"}
                                {preview.result.truncated ? " (scan capped)" : ""}
                            </Typography>
                            {preview.result.photos.length > 0 && (
                                <Stack spacing={0.25} sx={{ mt: 0.5 }}>
                                    {preview.result.photos.map((photo) => (
                                        <Typography key={`preview-${photo.photo_id}`} variant="caption" color="text.secondary">
                                            {photo.filename}
                                        </Typography>
                                    ))}
                                </Stack>
                            )}
                        </>
                    )}
                </Box>
            </Stack>
        </Box>
    );
}
