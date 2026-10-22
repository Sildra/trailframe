import { useCallback, useEffect, useMemo, useState } from "react";
import {
    Box,
    Button,
    Chip,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Divider,
    IconButton,
    Stack,
    Tab,
    Tabs,
    TextField,
    Tooltip,
    Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import SaveIcon from "@mui/icons-material/Save";
import UndoIcon from "@mui/icons-material/Undo";
import { api } from "../api/client";
import RulePage from "../components/RulePage";
import TagOverview from "../components/TagOverview";
import TagTree from "../components/TagTree";
import ThumbnailGallery from "../components/ThumbnailGallery";
import {
    addTag,
    buildTagTree,
    flattenTags,
    isTagUnder,
    moveTag,
    movedTagPath,
    removeTag,
    renameTag,
    renamedTagPath,
    tagParent,
    tagPaths,
    type TagCounts,
    type TagEntry,
    type TagNode,
} from "../lib/tags";

type TagView = "overview" | "editor" | "rules";

const NEW_TAG_NAME = "New tag";

interface TagNameFieldProps {
    value: string;
    onCommit: (name: string) => void;
}

function TagNameField({ value, onCommit }: TagNameFieldProps) {
    const [text, setText] = useState(value);

    return (
        <TextField
            label="Name"
            size="small"
            value={text}
            onChange={(event) => {
                setText(event.target.value);
                onCommit(event.target.value);
            }}
            helperText="Renaming moves the tag and every tag below it."
        />
    );
}

interface TagParentFieldProps {
    value: string;
    options: string[];
    onCommit: (parent: string) => void;
}

function TagParentField({ value, options, onCommit }: TagParentFieldProps) {
    const [text, setText] = useState(value);

    const commit = () => {
        onCommit(text);
    };

    return (
        <>
            <TextField
                label="Parent path"
                size="small"
                value={text}
                onChange={(event) => setText(event.target.value)}
                onBlur={commit}
                onKeyDown={(event) => {
                    if (event.key === "Enter") {
                        event.preventDefault();
                        commit();
                    }
                }}
                helperText="Leave empty for a root tag. Moving a tag moves everything below it."
                slotProps={{ htmlInput: { list: "tag-parent-options" } }}
            />
            <datalist id="tag-parent-options">
                {options.map((option) => (
                    <option key={option} value={option} />
                ))}
            </datalist>
        </>
    );
}

export default function TagsPage() {
    const [view, setView] = useState<TagView>("overview");
    const [draft, setDraft] = useState<TagEntry[] | null>(null);
    const [baseline, setBaseline] = useState<TagEntry[]>([]);
    const [counts, setCounts] = useState<Record<number, TagCounts>>({});
    const [selectedPath, setSelectedPath] = useState<string | null>(null);
    const [filter, setFilter] = useState("");
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [confirmDelete, setConfirmDelete] = useState(false);
    const [tagPhotos, setTagPhotos] = useState<{ key: string; ids: number[] }>({ key: "", ids: [] });

    const applyCounts = useCallback((tree: TagNode[]) => {
        const next: Record<number, TagCounts> = {};

        const walk = (nodes: TagNode[]) => {
            for (const node of nodes) {
                if (node.id != null) {
                    next[node.id] = { count: node.count, total: node.total };
                }
                walk(node.children ?? []);
            }
        };

        walk(tree);
        setCounts(next);
    }, []);

    const applyTree = useCallback(
        (tree: TagNode[]) => {
            const entries = flattenTags(tree);

            setDraft(entries);
            setBaseline(entries);
            applyCounts(tree);
        },
        [applyCounts],
    );

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/tags")
            .then(({ data, error: failure }) => {
                if (cancelled) {
                    return;
                }

                if (failure || !data) {
                    setError("The vocabulary could not be loaded.");
                    return;
                }

                applyTree(data);
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, [applyTree]);

    const tree = useMemo(() => (draft === null ? [] : buildTagTree(draft)), [draft]);
    const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(baseline), [draft, baseline]);

    const selected = useMemo(() => {
        if (draft === null || selectedPath === null) {
            return null;
        }

        return draft.find((entry) => entry.path === selectedPath) ?? null;
    }, [draft, selectedPath]);

    const selectedCounts = useMemo(() => {
        if (!selected || selected.id == null) {
            return { count: 0, total: 0 };
        }

        return counts[selected.id] ?? { count: 0, total: 0 };
    }, [selected, counts]);

    const descendants = useMemo(() => {
        if (draft === null || selectedPath === null) {
            return 0;
        }

        return draft.filter((entry) => entry.path !== selectedPath && entry.path.startsWith(`${selectedPath}/`)).length;
    }, [draft, selectedPath]);

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
    }, [selectedPath, baseline]);

    const photoIds = useMemo(
        () => (tagPhotos.key === selectedPath ? tagPhotos.ids : []),
        [tagPhotos, selectedPath],
    );

    const save = async () => {
        if (draft === null) {
            return;
        }

        setSaving(true);
        setError(null);
        setMessage(null);

        const { data, error: failure } = await api.PUT("/api/tags", { body: { tags: draft } });

        setSaving(false);

        if (failure || !data) {
            setError("The vocabulary could not be saved.");
            return;
        }

        applyTree(data);
        setMessage("Vocabulary saved.");
    };

    const revert = () => {
        setDraft(baseline.map((entry) => ({ ...entry })));
        setMessage(null);
        setError(null);
    };

    const quickAdd = async (path: string, description: string): Promise<string | null> => {
        setError(null);

        const { data, error: failure } = await api.POST("/api/tags", {
            body: { path, description: description || null },
        });

        if (failure || !data) {
            const detail = failure && typeof failure === "object" && "detail" in failure ? failure.detail : null;

            if (Array.isArray(detail)) {
                return "The tag path is invalid.";
            }

            return typeof detail === "string" ? detail : "The tag could not be added.";
        }

        const entries = flattenTags(data);

        if (dirty) {
            // The editor holds unsaved changes: keep them and add the new tag.
            setDraft((previous) => {
                if (previous === null) {
                    return entries;
                }

                const known = new Set(previous.map((entry) => entry.id).filter((id) => id != null));

                return [...previous, ...entries.filter((entry) => entry.id != null && !known.has(entry.id))];
            });
            applyCounts(data);
        } else {
            applyTree(data);
        }

        setMessage(`Added the tag "${path}".`);

        return null;
    };

    const updateSelected = (changes: Partial<TagEntry>) => {
        if (!selected || selectedPath === null) {
            return;
        }

        setDraft((previous) =>
            previous === null
                ? previous
                : previous.map((entry) => (entry.path === selectedPath ? { ...entry, ...changes } : entry)),
        );
    };

    const handleRename = (name: string) => {
        if (selectedPath === null) {
            return;
        }

        const target = renamedTagPath(selectedPath, name);

        setDraft((previous) => (previous === null ? previous : renameTag(previous, selectedPath, name)));

        if (target !== selectedPath) {
            setSelectedPath(target);
        }
    };

    const handleMove = (parent: string) => {
        if (selectedPath === null) {
            return;
        }

        const target = movedTagPath(selectedPath, parent);

        if (target === selectedPath || isTagUnder(target, selectedPath)) {
            return;
        }

        setDraft((previous) => (previous === null ? previous : moveTag(previous, selectedPath, parent)));
        setSelectedPath(target);
    };

    const handleAdd = (parent: string) => {
        if (draft === null) {
            return;
        }

        const path = parent ? `${parent}/${NEW_TAG_NAME}` : NEW_TAG_NAME;

        setDraft(addTag(draft, parent, NEW_TAG_NAME));
        setSelectedPath(path);
    };

    const handleDelete = () => {
        setConfirmDelete(false);

        if (selectedPath === null) {
            return;
        }

        setDraft((previous) => (previous === null ? previous : removeTag(previous, selectedPath)));
        setSelectedPath(null);
    };

    const parentOptions = useMemo(() => {
        if (draft === null) {
            return [];
        }

        return tagPaths(draft).filter((path) => path !== selectedPath);
    }, [draft, selectedPath]);

    if (draft === null) {
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
                    Tags
                </Typography>

                <Tabs
                    value={view}
                    onChange={(_event, value: TagView) => setView(value)}
                    sx={{ minHeight: 34, "& .MuiTab-root": { minHeight: 34, py: 0 } }}
                >
                    <Tab value="overview" label="Overview" />
                    <Tab value="editor" label="Vocabulary" />
                    <Tab value="rules" label="Rules" />
                </Tabs>

                {view === "editor" && (
                    <TextField
                        size="small"
                        value={filter}
                        onChange={(event) => setFilter(event.target.value)}
                        placeholder="Search the vocabulary"
                        sx={{ width: 220 }}
                    />
                )}

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
                {view === "overview" ? (
                    <Button size="small" variant="contained" startIcon={<AddIcon />} onClick={() => setView("editor")}>
                        Edit vocabulary
                    </Button>
                ) : view === "rules" ? null : (
                    <>
                        <Button size="small" startIcon={<AddIcon />} onClick={() => handleAdd("")}>
                            New tag
                        </Button>
                        <Button size="small" startIcon={<UndoIcon />} onClick={revert} disabled={!dirty}>
                            Revert
                        </Button>
                        <Button size="small" variant="contained" startIcon={<SaveIcon />} onClick={save} disabled={!dirty || saving}>
                            Save
                        </Button>
                    </>
                )}
            </Box>

            {view === "overview" ? (
                <TagOverview
                    tree={tree}
                    counts={counts}
                    paths={parentOptions}
                    onOpenTag={(path) => {
                        setSelectedPath(path);
                        setView("editor");
                    }}
                    onQuickAdd={quickAdd}
                />
            ) : view === "rules" ? (
                <RulePage tagEntries={draft ?? []} />
            ) : (
                <Box sx={{ flex: 1, minHeight: 0, display: "flex" }}>
                <Box sx={{ width: 340, flexShrink: 0, borderRight: 1, borderColor: "divider", overflowY: "auto" }}>
                    <TagTree
                        nodes={tree}
                        selectedPath={selectedPath}
                        onSelect={(node) => setSelectedPath(node.path)}
                        filter={filter}
                        emptyLabel="No tags yet — create one to get started."
                    />
                </Box>

                <Box sx={{ flex: 1, minWidth: 0, overflowY: "auto", p: 2 }}>
                    {selected === null ? (
                        <Typography color="text.secondary">Select a tag to edit it.</Typography>
                    ) : (
                        <Stack spacing={2} sx={{ maxWidth: 640 }}>
                            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                                    {selected.path}
                                </Typography>
                                <Box sx={{ flex: 1 }} />
                                <Button size="small" startIcon={<AddIcon />} onClick={() => handleAdd(selected.path)}>
                                    Add child
                                </Button>
                                <Tooltip title="Delete the tag and every tag below it">
                                    <IconButton
                                        size="small"
                                        color="error"
                                        aria-label="Delete tag"
                                        onClick={() => setConfirmDelete(true)}
                                    >
                                        <DeleteIcon fontSize="small" />
                                    </IconButton>
                                </Tooltip>
                            </Box>

                            <TagNameField
                                key={`name:${selected.path}`}
                                value={selected.path.split("/").pop() ?? ""}
                                onCommit={handleRename}
                            />

                            <TagParentField
                                key={`parent:${selected.path}`}
                                value={tagParent(selected.path)}
                                options={parentOptions}
                                onCommit={handleMove}
                            />

                            <TextField
                                label="Description"
                                size="small"
                                multiline
                                minRows={2}
                                value={selected.description ?? ""}
                                onChange={(event) => updateSelected({ description: event.target.value || null })}
                            />

                            <Box sx={{ display: "flex", gap: 2 }}>
                                <Chip size="small" label={`${selectedCounts.count} photos`} />
                                <Chip size="small" label={`${selectedCounts.total} including descendants`} />
                                <Chip size="small" label={`${descendants} descendant tags`} />
                            </Box>

                            <Divider />

                            <Box>
                                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                                    Photos ({photoIds.length})
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
                    )}
                </Box>
                </Box>
            )}

            <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)}>
                <DialogTitle>Delete tag</DialogTitle>
                <DialogContent>
                    <Typography>
                        Delete &ldquo;{selectedPath}&rdquo;?
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                        {descendants} descendant tag{descendants === 1 ? "" : "s"} and{" "}
                        {selectedCounts.total} photo{selectedCounts.total === 1 ? "" : "s"} will lose the tag. The change is
                        applied when the vocabulary is saved.
                    </Typography>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setConfirmDelete(false)}>Cancel</Button>
                    <Button color="error" onClick={handleDelete}>
                        Delete
                    </Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
}
