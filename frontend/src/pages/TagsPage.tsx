import { useCallback, useEffect, useMemo, useState } from "react";
import {
    Box,
    Button,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Divider,
    IconButton,
    Stack,
    Switch,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Tooltip,
    Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import BoltIcon from "@mui/icons-material/Bolt";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import RulePage from "../components/RulePage";
import TagOverview from "../components/TagOverview";
import ThumbnailGallery from "../components/ThumbnailGallery";
import { flattenTags, type TagCounts, type TagNode } from "../lib/tags";

type TagView = "overview" | "detail" | "rule";

type TagRule = components["schemas"]["RuleResponse"];

export default function TagsPage() {
    const [view, setView] = useState<TagView>("overview");
    const [tree, setTree] = useState<TagNode[] | null>(null);
    const [counts, setCounts] = useState<Record<number, TagCounts>>({});
    const [rules, setRules] = useState<TagRule[]>([]);
    const [selectedPath, setSelectedPath] = useState<string | null>(null);
    const [editingRule, setEditingRule] = useState<TagRule | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [confirmDelete, setConfirmDelete] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [applying, setApplying] = useState(false);
    const [tagPhotos, setTagPhotos] = useState<{ key: string; ids: number[] }>({ key: "", ids: [] });

    const applyTree = useCallback((nodes: TagNode[]) => {
        const next: Record<number, TagCounts> = {};

        const walk = (list: TagNode[]) => {
            for (const node of list) {
                if (node.id != null) {
                    next[node.id] = { count: node.count, total: node.total };
                }
                walk(node.children ?? []);
            }
        };

        walk(nodes);
        setTree(nodes);
        setCounts(next);
    }, []);

    const loadTree = useCallback(() => {
        api.GET("/api/tags")
            .then(({ data, error: failure }) => {
                if (failure || !data) {
                    setError("The vocabulary could not be loaded.");
                    return;
                }

                applyTree(data);
            })
            .catch(() => {});
    }, [applyTree]);

    const loadRules = useCallback(() => {
        api.GET("/api/rules")
            .then(({ data, error: failure }) => {
                if (failure || !data) {
                    setError("The rules could not be loaded.");
                    return;
                }

                setRules(data);
            })
            .catch(() => {});
    }, []);

    useEffect(() => loadTree(), [loadTree]);
    useEffect(() => loadRules(), [loadRules]);

    const entries = useMemo(() => (tree === null ? [] : flattenTags(tree)), [tree]);

    const selected = useMemo(() => {
        if (selectedPath === null) {
            return null;
        }

        const find = (nodes: TagNode[]): TagNode | null => {
            for (const node of nodes) {
                if (node.path === selectedPath) {
                    return node;
                }

                const match = find(node.children ?? []);

                if (match !== null) {
                    return match;
                }
            }

            return null;
        };

        return find(tree ?? []);
    }, [selectedPath, tree]);

    const tagRules = useMemo(() => {
        if (selected === null) {
            return [];
        }

        return rules
            .filter((rule) => rule.tag === selected.path)
            .sort((left, right) => left.name.localeCompare(right.name));
    }, [rules, selected]);

    useEffect(() => {
        if (selectedPath === null) {
            return;
        }

        let cancelled = false;

        api.GET("/api/photos/ids", { params: { query: { tags: [selectedPath] } } })
            .then(({ data, error: failure }) => {
                if (cancelled || failure || !data) {
                    return;
                }
                setTagPhotos({ key: selectedPath, ids: data });
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, [selectedPath]);

    const photoIds = useMemo(
        () => (tagPhotos.key === selectedPath ? tagPhotos.ids : []),
        [tagPhotos, selectedPath],
    );

    const openTag = (path: string) => {
        setSelectedPath(path);
        setView("detail");
        setEditingRule(null);
        setMessage(null);
        setError(null);
        loadRules();
    };

    const backToOverview = () => {
        setSelectedPath(null);
        setView("overview");
        setEditingRule(null);
    };

    const backToTag = () => {
        setView("detail");
        setEditingRule(null);
    };

    const quickAdd = async (path: string): Promise<string | null> => {
        setError(null);

        const { data, error: failure } = await api.POST("/api/tags", { body: { path } });

        if (failure || !data) {
            const detail = failure && typeof failure === "object" && "detail" in failure ? failure.detail : null;

            if (Array.isArray(detail)) {
                return "The tag path is invalid.";
            }

            return typeof detail === "string" ? detail : "The tag could not be added.";
        }

        applyTree(data);
        setMessage(`Added the tag "${path}".`);

        return null;
    };

    const deleteTag = async () => {
        setConfirmDelete(false);

        if (selected?.id == null) {
            return;
        }

        setDeleting(true);
        setError(null);
        setMessage(null);

        const { error: failure } = await api.DELETE("/api/tags/{tag_id}", {
            params: { path: { tag_id: selected.id } },
        });

        setDeleting(false);

        if (failure) {
            setError("The tag could not be deleted.");
            return;
        }

        backToOverview();
        setMessage("Tag deleted.");
        loadTree();
        loadRules();
    };

    const toggleRule = async (rule: TagRule) => {
        if (rule.id == null) {
            return;
        }

        setError(null);

        const { error: failure } = await api.PUT("/api/rules/{rule_id}", {
            params: { path: { rule_id: rule.id } },
            body: {
                tag: rule.tag,
                name: rule.name,
                description: rule.description,
                enabled: !rule.enabled,
                priority: rule.priority,
                expression: rule.expression,
                definition: rule.definition,
            },
        });

        if (failure) {
            setError("The rule could not be updated.");
            return;
        }

        loadRules();
    };

    const deleteRule = async (rule: TagRule) => {
        if (rule.id == null) {
            return;
        }

        setError(null);
        setMessage(null);

        const { error: failure } = await api.DELETE("/api/rules/{rule_id}", {
            params: { path: { rule_id: rule.id } },
        });

        if (failure) {
            setError("The rule could not be deleted.");
            return;
        }

        setMessage(`Deleted the rule "${rule.name}".`);
        loadRules();
    };

    const applyRules = async () => {
        setApplying(true);
        setError(null);
        setMessage(null);

        const { data, error: failure } = await api.POST("/api/rules/apply");

        setApplying(false);

        if (failure || !data) {
            setError("The rules could not be applied.");
            return;
        }

        setMessage(
            `Applied the rules to ${data.photos} photo${data.photos === 1 ? "" : "s"}: ${data.changed} received a tag, ${data.added} tag${data.added === 1 ? "" : "s"} added.`,
        );
    };

    if (tree === null) {
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
                <Typography variant="h6">Tags</Typography>

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
            </Box>

            {view === "rule" && selected !== null ? (
                <RulePage
                    key={`${selected.path}:${editingRule?.id ?? "new"}`}
                    tagPath={selected.path}
                    rule={editingRule}
                    onBack={backToTag}
                    onSaved={() => {
                        backToTag();
                        setMessage("Rule saved.");
                        loadRules();
                        loadTree();
                    }}
                />
            ) : view === "detail" && selected !== null ? (
                <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto", p: 2 }}>
                    <Stack spacing={2} sx={{ maxWidth: 960, width: "100%", mx: "auto" }}>
                        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                            <Tooltip title="Back to the overview">
                                <IconButton size="small" aria-label="Back to overview" onClick={backToOverview}>
                                    <ArrowBackIcon fontSize="small" />
                                </IconButton>
                            </Tooltip>
                            <Typography variant="h6" sx={{ fontWeight: 600, wordBreak: "break-word" }}>
                                {selected.path}
                            </Typography>
                            <Box sx={{ flex: 1 }} />
                            <Tooltip title="Delete the tag and every tag below it">
                                <span>
                                    <IconButton
                                        size="small"
                                        color="error"
                                        aria-label="Delete tag"
                                        disabled={deleting}
                                        onClick={() => setConfirmDelete(true)}
                                    >
                                        <DeleteIcon fontSize="small" />
                                    </IconButton>
                                </span>
                            </Tooltip>
                        </Box>

                        <Box>
                            <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}>
                                <Typography variant="subtitle2">Rules</Typography>
                                <Box sx={{ flex: 1 }} />
                                <Button
                                    size="small"
                                    startIcon={<AddIcon />}
                                    onClick={() => {
                                        setEditingRule(null);
                                        setView("rule");
                                    }}
                                >
                                    New rule
                                </Button>
                                <Tooltip title="Apply every enabled rule to the photos already in the library">
                                    <span>
                                        <Button
                                            size="small"
                                            startIcon={<BoltIcon />}
                                            onClick={applyRules}
                                            disabled={applying}
                                        >
                                            Apply to all photos
                                        </Button>
                                    </span>
                                </Tooltip>
                            </Box>

                            {tagRules.length === 0 ? (
                                <Typography variant="body2" color="text.secondary">
                                    No rule assigns this tag yet.
                                </Typography>
                            ) : (
                                <TableContainer sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
                                    <Table>
                                        <TableHead>
                                            <TableRow>
                                                <TableCell>Rule</TableCell>
                                                <TableCell align="center" sx={{ width: 80 }}>
                                                    On
                                                </TableCell>
                                                <TableCell align="right" sx={{ width: 100 }} />
                                            </TableRow>
                                        </TableHead>
                                        <TableBody>
                                            {tagRules.map((rule) => (
                                                <TableRow key={`rule-${rule.id ?? rule.name}`} hover>
                                                    <TableCell>
                                                        <Typography
                                                            variant="body2"
                                                            sx={{ cursor: "pointer", fontWeight: 500 }}
                                                            onClick={() => {
                                                                setEditingRule(rule);
                                                                setView("rule");
                                                            }}
                                                        >
                                                            {rule.name}
                                                        </Typography>
                                                    </TableCell>
                                                    <TableCell align="center">
                                                        <Switch
                                                            size="small"
                                                            checked={rule.enabled}
                                                            onChange={() => toggleRule(rule)}
                                                            slotProps={{
                                                                input: { "aria-label": `Enable ${rule.name}` },
                                                            }}
                                                        />
                                                    </TableCell>
                                                    <TableCell align="right">
                                                        <Tooltip title="Edit the rule">
                                                            <IconButton
                                                                size="small"
                                                                aria-label="Edit rule"
                                                                onClick={() => {
                                                                    setEditingRule(rule);
                                                                    setView("rule");
                                                                }}
                                                            >
                                                                <EditIcon fontSize="small" />
                                                            </IconButton>
                                                        </Tooltip>
                                                        <Tooltip title="Delete the rule">
                                                            <IconButton
                                                                size="small"
                                                                color="error"
                                                                aria-label="Delete rule"
                                                                onClick={() => deleteRule(rule)}
                                                            >
                                                                <DeleteIcon fontSize="small" />
                                                            </IconButton>
                                                        </Tooltip>
                                                    </TableCell>
                                                </TableRow>
                                            ))}
                                        </TableBody>
                                    </Table>
                                </TableContainer>
                            )}
                        </Box>

                        <Divider />

                        <Box>
                            <Typography variant="subtitle2" sx={{ mb: 1 }}>
                                Photos
                            </Typography>
                            {photoIds.length === 0 ? (
                                <Typography variant="body2" color="text.secondary">
                                    No photo carries this tag yet.
                                </Typography>
                            ) : (
                                <ThumbnailGallery photoIds={photoIds} selectedPhotoId={null} onSelect={() => {}} />
                            )}
                        </Box>
                    </Stack>
                </Box>
            ) : (
                <TagOverview
                    tree={tree}
                    counts={counts}
                    paths={entries.map((entry) => entry.path)}
                    onOpenTag={openTag}
                    onQuickAdd={quickAdd}
                />
            )}

            <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)}>
                <DialogTitle>Delete tag</DialogTitle>
                <DialogContent>
                    <Typography>Delete &ldquo;{selected?.path}&rdquo;?</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                        Every tag below it is deleted too, and the photos carrying them lose the tag.
                    </Typography>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setConfirmDelete(false)}>Cancel</Button>
                    <Button color="error" onClick={deleteTag}>
                        Delete
                    </Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
}
