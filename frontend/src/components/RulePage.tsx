import { useCallback, useEffect, useMemo, useState } from "react";
import {
    Box,
    Button,
    Chip,
    CircularProgress,
    Divider,
    IconButton,
    Stack,
    Switch,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    Tooltip,
    Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import SaveIcon from "@mui/icons-material/Save";
import UndoIcon from "@mui/icons-material/Undo";
import BoltIcon from "@mui/icons-material/Bolt";
import { api } from "../api/client";
import RuleBuilder from "../components/RuleBuilder";
import {
    describeRule,
    emptyRule,
    toDraft,
    toPayload,
    type RuleDraft,
    type TagRule,
    type TagRuleField,
    type TagRuleTestMatch,
} from "../lib/rules";
import { tagPaths, type TagEntry } from "../lib/tags";

export interface RulePageProps {
    /** The vocabulary paths, offered when picking the tags a rule assigns. */
    tagEntries: TagEntry[];
}

export default function RulePage({ tagEntries }: RulePageProps) {
    const [rules, setRules] = useState<TagRule[] | null>(null);
    const [fields, setFields] = useState<TagRuleField[]>([]);
    const [draft, setDraft] = useState<RuleDraft | null>(null);
    const [baseline, setBaseline] = useState<RuleDraft | null>(null);
    const [matches, setMatches] = useState<TagRuleTestMatch[] | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [applying, setApplying] = useState(false);

    const tagOptions = useMemo(() => tagPaths(tagEntries), [tagEntries]);

    const loadRules = useCallback(() => {
        let cancelled = false;

        api.GET("/api/tag-rules")
            .then(({ data, error: failure }) => {
                if (cancelled) {
                    return;
                }

                if (failure || !data) {
                    setError("The rules could not be loaded.");
                    return;
                }

                setRules(data);
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => loadRules(), [loadRules]);

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/tag-rules/fields")
            .then(({ data, error: failure }) => {
                if (cancelled || failure || !data) {
                    return;
                }

                setFields(data);
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, []);

    const dirty = useMemo(
        () => draft !== null && baseline !== null && JSON.stringify(draft) !== JSON.stringify(baseline),
        [draft, baseline],
    );

    const edit = (rule: TagRule) => {
        const next = toDraft(rule);

        setDraft(next);
        setBaseline(next);
        setMatches(null);
        setError(null);
        setMessage(null);
    };

    const create = () => {
        const next = emptyRule();

        setDraft(next);
        setBaseline(next);
        setMatches(null);
        setError(null);
        setMessage(null);
    };

    const revert = () => {
        if (baseline === null) {
            return;
        }

        setDraft({ ...baseline, conditions: baseline.conditions.map((condition) => ({ ...condition })) });
        setMatches(null);
        setError(null);
    };

    const save = async () => {
        if (draft === null) {
            return;
        }

        setSaving(true);
        setError(null);
        setMessage(null);

        const payload = toPayload(draft);
        const response =
            draft.id === null
                ? await api.POST("/api/tag-rules", { body: payload })
                : await api.PUT("/api/tag-rules/{rule_id}", { params: { path: { rule_id: draft.id } }, body: payload });

        setSaving(false);

        if (response.error || !response.data) {
            setError("The rule could not be saved.");
            return;
        }

        setDraft(toDraft(response.data));
        setBaseline(toDraft(response.data));
        setMessage("Rule saved.");
        loadRules();
    };

    const remove = async (rule: TagRule) => {
        if (rule.id == null) {
            return;
        }

        const { error: failure } = await api.DELETE("/api/tag-rules/{rule_id}", { params: { path: { rule_id: rule.id } } });

        if (failure) {
            setError("The rule could not be deleted.");
            return;
        }

        setMessage("Rule deleted.");
        setError(null);
        loadRules();
    };

    const toggle = async (rule: TagRule) => {
        if (rule.id == null) {
            return;
        }

        const payload = {
            name: rule.name,
            enabled: !rule.enabled,
            priority: rule.priority,
            description: rule.description,
            conditions: rule.conditions,
            tags: rule.tags,
        };

        const { error: failure } = await api.PUT("/api/tag-rules/{rule_id}", {
            params: { path: { rule_id: rule.id } },
            body: payload,
        });

        if (failure) {
            setError("The rule could not be updated.");
            return;
        }

        loadRules();
    };

    const test = async () => {
        if (draft === null) {
            return;
        }

        setTesting(true);
        setError(null);
        setMatches(null);

        const { data, error: failure } = await api.POST("/api/tag-rules/test", {
            body: { rule: toPayload(draft), limit: 25 },
        });

        setTesting(false);

        if (failure || !data) {
            setError("The rule could not be tested.");
            return;
        }

        setMatches(data);
    };

    const apply = async () => {
        setApplying(true);
        setError(null);
        setMessage(null);

        const { data, error: failure } = await api.POST("/api/tag-rules/apply");

        setApplying(false);

        if (failure || !data) {
            setError("The rules could not be applied.");
            return;
        }

        setMessage(
            `Applied the rules to ${data.photos} photo${data.photos === 1 ? "" : "s"}: ${data.changed} received a tag, ${data.added} tag${data.added === 1 ? "" : "s"} added.`,
        );
    };

    if (rules === null) {
        return (
            <Box sx={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <CircularProgress />
            </Box>
        );
    }

    return (
        <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
            <Box
                sx={{
                    display: "flex",
                    alignItems: "center",
                    gap: 1,
                    px: 2,
                    py: 1,
                    borderBottom: 1,
                    borderColor: "divider",
                    flexWrap: "wrap",
                }}
            >
                <Typography variant="h6" sx={{ mr: 1 }}>
                    Rules
                </Typography>

                <Box sx={{ flex: 1 }} />

                {message && (
                    <Typography variant="caption" color="success.main">
                        {message}
                    </Typography>
                )}
                {error && (
                    <Typography variant="caption" color="error.main">
                        {error}
                    </Typography>
                )}

                {draft !== null && (
                    <>
                        <Button size="small" startIcon={<UndoIcon />} onClick={revert} disabled={!dirty}>
                            Revert
                        </Button>
                        <Button
                            size="small"
                            startIcon={<PlayArrowIcon />}
                            onClick={test}
                            disabled={testing}
                        >
                            Test
                        </Button>
                        <Button
                            size="small"
                            variant="contained"
                            startIcon={<SaveIcon />}
                            onClick={save}
                            disabled={!dirty || saving}
                        >
                            Save
                        </Button>
                    </>
                )}
                <Button size="small" startIcon={<AddIcon />} onClick={create}>
                    New rule
                </Button>
                <Button size="small" startIcon={<BoltIcon />} onClick={apply} disabled={applying}>
                    Apply to all photos
                </Button>
            </Box>

            <Box sx={{ flex: 1, minHeight: 0, display: "flex" }}>
                <Box sx={{ width: 380, flexShrink: 0, borderRight: 1, borderColor: "divider", overflowY: "auto" }}>
                    {rules.length === 0 ? (
                        <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
                            No rule yet. A rule assigns tags to the photos whose metadata matches it.
                        </Typography>
                    ) : (
                        <Table size="small">
                            <TableHead>
                                <TableRow>
                                    <TableCell>Rule</TableCell>
                                    <TableCell align="right">Priority</TableCell>
                                    <TableCell align="center">On</TableCell>
                                    <TableCell align="right" />
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {rules.map((rule) => {
                                    const active = draft?.id != null && draft.id === rule.id;

                                    return (
                                        <TableRow key={`rule-${rule.id}`} hover selected={active}>
                                            <TableCell>
                                                <Typography
                                                    variant="body2"
                                                    sx={{ cursor: "pointer", fontWeight: active ? 600 : 400 }}
                                                    onClick={() => edit(rule)}
                                                >
                                                    {rule.name}
                                                </Typography>
                                                <Typography variant="caption" color="text.secondary">
                                                    {describeRule(toDraft(rule), fields)}
                                                </Typography>
                                                <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: "wrap", gap: 0.5 }}>
                                                    {rule.tags.map((tag) => (
                                                        <Chip key={`rule-list-tag-${rule.id}-${tag}`} size="small" label={tag} />
                                                    ))}
                                                </Stack>
                                            </TableCell>
                                            <TableCell align="right">{rule.priority}</TableCell>
                                            <TableCell align="center">
                                                <Switch
                                                    size="small"
                                                    checked={rule.enabled}
                                                    onChange={() => toggle(rule)}
                                                    slotProps={{ input: { "aria-label": `Enable ${rule.name}` } }}
                                                />
                                            </TableCell>
                                            <TableCell align="right">
                                                <Tooltip title="Edit the rule">
                                                    <IconButton size="small" aria-label="Edit rule" onClick={() => edit(rule)}>
                                                        <EditIcon fontSize="small" />
                                                    </IconButton>
                                                </Tooltip>
                                                <Tooltip title="Delete the rule">
                                                    <IconButton
                                                        size="small"
                                                        color="error"
                                                        aria-label="Delete rule"
                                                        onClick={() => remove(rule)}
                                                    >
                                                        <DeleteIcon fontSize="small" />
                                                    </IconButton>
                                                </Tooltip>
                                            </TableCell>
                                        </TableRow>
                                    );
                                })}
                            </TableBody>
                        </Table>
                    )}
                </Box>

                <Box sx={{ flex: 1, minWidth: 0, overflowY: "auto", p: 2 }}>
                    {draft === null ? (
                        <Typography color="text.secondary">
                            Select a rule to edit it, or create one to assign tags automatically.
                        </Typography>
                    ) : (
                        <Stack spacing={2} sx={{ maxWidth: 780 }}>
                            <RuleBuilder draft={draft} fields={fields} onChange={setDraft} tagOptions={tagOptions} />

                            {matches !== null && (
                                <>
                                    <Divider />
                                    <Box>
                                        <Typography variant="subtitle2" sx={{ mb: 1 }}>
                                            Test result — {matches.length} matching photo
                                            {matches.length === 1 ? "" : "s"}
                                        </Typography>
                                        {matches.length === 0 ? (
                                            <Typography variant="body2" color="text.secondary">
                                                No photo in the library matches this rule.
                                            </Typography>
                                        ) : (
                                            <Stack spacing={0.5}>
                                                {matches.map((match) => (
                                                    <Stack
                                                        key={`match-${match.photo_id}`}
                                                        direction="row"
                                                        spacing={1}
                                                        sx={{ alignItems: "center" }}
                                                    >
                                                        <Typography variant="body2" sx={{ flex: 1, minWidth: 0 }}>
                                                            {match.filename}
                                                        </Typography>
                                                        {match.tags.map((tag) => (
                                                            <Chip key={`match-tag-${match.photo_id}-${tag}`} size="small" label={tag} />
                                                        ))}
                                                    </Stack>
                                                ))}
                                            </Stack>
                                        )}
                                    </Box>
                                </>
                            )}
                        </Stack>
                    )}
                </Box>
            </Box>
        </Box>
    );
}
