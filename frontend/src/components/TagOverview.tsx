import { useMemo, useState } from "react";
import {
    Box,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    InputAdornment,
    MenuItem,
    Select,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TextField,
    Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import SearchIcon from "@mui/icons-material/Search";
import { normalizeTagPath, tagRows, type TagCounts, type TagNode } from "../lib/tags";

type Scope = "all" | "roots" | "used";
type SortKey = "path" | "count" | "total";

interface TagOverviewProps {
    /** The vocabulary, as a tree. */
    tree: TagNode[];
    /** The number of photos using each tag, by tag id. */
    counts: Record<number, TagCounts>;
    /** Every path of the vocabulary, for the quick add suggestions. */
    paths: string[];
    /** Open the vocabulary editor on a tag. */
    onOpenTag: (path: string) => void;
    /** Add a tag to the vocabulary. Returns the error message, or null on success. */
    onQuickAdd: (path: string, description: string) => Promise<string | null>;
}

interface StatProps {
    label: string;
    value: number;
}

function Stat({ label, value }: StatProps) {
    return (
        <Box
            sx={{
                minWidth: 130,
                px: 2,
                py: 1.25,
                border: 1,
                borderColor: "divider",
                borderRadius: 1,
            }}
        >
            <Typography variant="h6" sx={{ lineHeight: 1.2 }}>
                {value}
            </Typography>
            <Typography variant="caption" color="text.secondary">
                {label}
            </Typography>
        </Box>
    );
}

interface QuickAddDialogProps {
    open: boolean;
    paths: string[];
    onClose: () => void;
    onAdd: (path: string, description: string) => Promise<string | null>;
}

function QuickAddDialog({ open, paths, onClose, onAdd }: QuickAddDialogProps) {
    const [path, setPath] = useState("");
    const [description, setDescription] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    const normalized = normalizeTagPath(path);
    const missing = useMemo(() => {
        if (!normalized) {
            return [];
        }

        const segments = normalized.split("/");
        const ancestors = segments.slice(0, -1).map((_segment, index) => segments.slice(0, index + 1).join("/"));

        return ancestors.filter((ancestor) => !paths.includes(ancestor));
    }, [normalized, paths]);

    const submit = async () => {
        if (!normalized) {
            setError("A tag path is required.");
            return;
        }

        setSaving(true);
        setError(null);

        const failure = await onAdd(normalized, description.trim());

        setSaving(false);

        if (failure) {
            setError(failure);
            return;
        }

        setPath("");
        setDescription("");
    };

    return (
        <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
            <DialogTitle>Quick add a tag</DialogTitle>
            <DialogContent>
                <Stack spacing={2} sx={{ mt: 1 }}>
                    <TextField
                        label="Tag path"
                        size="small"
                        autoFocus
                        value={path}
                        onChange={(event) => setPath(event.target.value)}
                        placeholder="Landscape/Mountain/Peak"
                        helperText="Use a slash to nest the tag. The missing parents are created as well."
                        slotProps={{ htmlInput: { list: "quick-add-tag-paths" } }}
                    />
                    <datalist id="quick-add-tag-paths">
                        {paths.map((option) => (
                            <option key={option} value={option} />
                        ))}
                    </datalist>

                    <TextField
                        label="Description"
                        size="small"
                        value={description}
                        onChange={(event) => setDescription(event.target.value)}
                        placeholder="What this tag covers"
                    />

                    {normalized && (
                        <Box sx={{ px: 1, py: 0.5 }}>
                            <Typography variant="body2">
                                New tag: <strong>{normalized}</strong>
                            </Typography>
                            {missing.length > 0 && (
                                <Typography variant="caption" color="text.secondary">
                                    The missing parents are created too: {missing.join(", ")}
                                </Typography>
                            )}
                        </Box>
                    )}

                    {error && (
                        <Typography variant="body2" color="error.main">
                            {error}
                        </Typography>
                    )}
                </Stack>
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose}>Cancel</Button>
                <Button variant="contained" onClick={submit} disabled={saving || !normalized}>
                    Add tag
                </Button>
            </DialogActions>
        </Dialog>
    );
}

export default function TagOverview({ tree, counts, paths, onOpenTag, onQuickAdd }: TagOverviewProps) {
    const [query, setQuery] = useState("");
    const [scope, setScope] = useState<Scope>("all");
    const [sort, setSort] = useState<{ key: SortKey; direction: "asc" | "desc" }>({ key: "path", direction: "asc" });
    const [quickAddOpen, setQuickAddOpen] = useState(false);

    const stats = useMemo(() => {
        const rows = tagRows(tree, counts);

        return {
            total: rows.length,
            roots: rows.filter((row) => row.depth === 0).length,
            used: rows.filter((row) => row.count > 0).length,
            assignments: rows.reduce((sum, row) => sum + row.count, 0),
        };
    }, [tree, counts]);

    const rows = useMemo(() => {
        const needle = query.trim().toLowerCase();

        let visible = tagRows(tree, counts);

        if (scope === "roots") {
            visible = visible.filter((row) => row.depth === 0);
        }

        if (scope === "used") {
            visible = visible.filter((row) => row.count > 0);
        }

        if (needle) {
            visible = visible.filter(
                (row) =>
                    row.path.toLowerCase().includes(needle) ||
                    row.name.toLowerCase().includes(needle) ||
                    (row.description ?? "").toLowerCase().includes(needle),
            );
        }

        const factor = sort.direction === "asc" ? 1 : -1;

        return [...visible].sort((left, right) => {
            if (sort.key === "path") {
                return left.path.localeCompare(right.path) * factor;
            }

            return (left[sort.key] - right[sort.key]) * factor;
        });
    }, [tree, counts, query, scope, sort]);

    const toggleSort = (key: SortKey) => {
        setSort((previous) =>
            previous.key === key
                ? { key, direction: previous.direction === "asc" ? "desc" : "asc" }
                : { key, direction: "asc" },
        );
    };

    const sortMark = (key: SortKey) => (sort.key === key ? (sort.direction === "asc" ? " ▲" : " ▼") : "");

    return (
        <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto", p: 2, display: "flex", flexDirection: "column", gap: 2 }}>
            <Box sx={{ display: "flex", gap: 1.5, flexWrap: "wrap" }}>
                <Stat label="Tags" value={stats.total} />
                <Stat label="Root tags" value={stats.roots} />
                <Stat label="Tags in use" value={stats.used} />
                <Stat label="Photo assignments" value={stats.assignments} />
            </Box>

            <Box sx={{ display: "flex", gap: 1, alignItems: "center", flexWrap: "wrap" }}>
                <TextField
                    size="small"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search the vocabulary"
                    slotProps={{
                        input: {
                            startAdornment: (
                                <InputAdornment position="start">
                                    <SearchIcon fontSize="small" />
                                </InputAdornment>
                            ),
                        },
                    }}
                    sx={{ width: 260 }}
                />

                <Select size="small" value={scope} onChange={(event) => setScope(event.target.value as Scope)}>
                    <MenuItem value="all">All tags</MenuItem>
                    <MenuItem value="roots">Root tags</MenuItem>
                    <MenuItem value="used">Tags in use</MenuItem>
                </Select>

                <Typography variant="caption" color="text.secondary">
                    {rows.length} of {stats.total} tags
                </Typography>

                <Box sx={{ flex: 1 }} />

                <Button variant="contained" startIcon={<AddIcon />} onClick={() => setQuickAddOpen(true)}>
                    Quick add
                </Button>
            </Box>

            <TableContainer sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
                <Table size="small" stickyHeader>
                    <TableHead>
                        <TableRow>
                            <TableCell onClick={() => toggleSort("path")} sx={{ cursor: "pointer", userSelect: "none" }}>
                                Tag{sortMark("path")}
                            </TableCell>
                            <TableCell>Path</TableCell>
                            <TableCell>Description</TableCell>
                            <TableCell align="right" onClick={() => toggleSort("count")} sx={{ cursor: "pointer", userSelect: "none" }}>
                                Photos{sortMark("count")}
                            </TableCell>
                            <TableCell align="right" onClick={() => toggleSort("total")} sx={{ cursor: "pointer", userSelect: "none" }}>
                                With descendants{sortMark("total")}
                            </TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {rows.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={5}>
                                    <Typography variant="body2" color="text.secondary">
                                        No tag matches the filter.
                                    </Typography>
                                </TableCell>
                            </TableRow>
                        ) : (
                            rows.map((row) => (
                                <TableRow
                                    key={row.path}
                                    hover
                                    onClick={() => onOpenTag(row.path)}
                                    sx={{ cursor: "pointer" }}
                                >
                                    <TableCell sx={{ pl: 2 + row.depth * 1.75 }}>
                                        {row.name}
                                    </TableCell>
                                    <TableCell sx={{ fontFamily: "monospace", fontSize: 12, color: "text.secondary" }}>
                                        {row.path}
                                    </TableCell>
                                    <TableCell sx={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis" }}>
                                        {row.description ?? ""}
                                    </TableCell>
                                    <TableCell align="right">{row.count}</TableCell>
                                    <TableCell align="right">{row.total}</TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>
            </TableContainer>

            <QuickAddDialog
                key={quickAddOpen ? "quick-add-open" : "quick-add-closed"}
                open={quickAddOpen}
                paths={paths}
                onClose={() => setQuickAddOpen(false)}
                onAdd={onQuickAdd}
            />
        </Box>
    );
}
