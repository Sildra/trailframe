import { useMemo, useState } from "react";
import {
    Box,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    MenuItem,
    Select,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import AddIcon from "@mui/icons-material/Add";
import { normalizeTagPath, tagRows, type TagCounts, type TagNode, type TagRow } from "../lib/tags";

type Scope = "all" | "roots" | "used";

interface TagOverviewProps {
    /** The vocabulary, as a tree. */
    tree: TagNode[];
    /** The number of photos using each tag, by tag id. */
    counts: Record<number, TagCounts>;
    /** Every path of the vocabulary, for the quick add suggestions. */
    paths: string[];
    /** Open the tag's inner page. */
    onOpenTag: (path: string) => void;
    /** Add a tag to the vocabulary. Returns the error message, or null on success. */
    onQuickAdd: (path: string) => Promise<string | null>;
}

interface QuickAddDialogProps {
    open: boolean;
    paths: string[];
    onClose: () => void;
    onAdd: (path: string) => Promise<string | null>;
}

function QuickAddDialog({ open, paths, onClose, onAdd }: QuickAddDialogProps) {
    const [path, setPath] = useState("");
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

        const failure = await onAdd(normalized);

        setSaving(false);

        if (failure) {
            setError(failure);
            return;
        }

        setPath("");
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

const COLUMNS: GridColDef<TagRow>[] = [
    {
        field: "name",
        headerName: "Tag",
        flex: 1,
        minWidth: 200,
        valueGetter: (_value, row) => row.name,
        renderCell: (params) => <Box sx={{ pl: (params.row.depth ?? 0) * 1.75 }}>{params.row.name}</Box>,
    },
    {
        field: "path",
        headerName: "Path",
        flex: 1,
        minWidth: 220,
        renderCell: (params) => (
            <Typography variant="caption" sx={{ fontFamily: "monospace", color: "text.secondary" }}>
                {params.row.path}
            </Typography>
        ),
    },
    {
        field: "rules",
        headerName: "Rules",
        width: 90,
        type: "number",
    },
    { field: "count", headerName: "Photos", width: 90, type: "number" },
    { field: "total", headerName: "With descendants", width: 150, type: "number" },
];

export default function TagOverview({ tree, counts, paths, onOpenTag, onQuickAdd }: TagOverviewProps) {
    const [scope, setScope] = useState<Scope>("all");
    const [quickAddOpen, setQuickAddOpen] = useState(false);

    const allRows = useMemo(() => tagRows(tree, counts), [tree, counts]);

    const rows = useMemo(() => {
        if (scope === "roots") {
            return allRows.filter((row) => row.depth === 0);
        }

        if (scope === "used") {
            return allRows.filter((row) => row.count > 0);
        }

        return allRows;
    }, [allRows, scope]);

    return (
        <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 1.5, p: 2 }}>
            <Box sx={{ display: "flex", gap: 1, alignItems: "center", flexWrap: "wrap" }}>
                <Select size="small" value={scope} onChange={(event) => setScope(event.target.value as Scope)}>
                    <MenuItem value="all">All tags</MenuItem>
                    <MenuItem value="roots">Root tags</MenuItem>
                    <MenuItem value="used">Tags in use</MenuItem>
                </Select>

                <Typography variant="caption" color="text.secondary">
                    {rows.length} of {allRows.length} tags
                </Typography>

                <Box sx={{ flex: 1 }} />

                <Button variant="contained" startIcon={<AddIcon />} onClick={() => setQuickAddOpen(true)}>
                    Quick add
                </Button>
            </Box>

            <DataGrid
                rows={rows}
                columns={COLUMNS}
                getRowId={(row) => row.path}
                initialState={{
                    sorting: { sortModel: [{ field: "path", sort: "asc" }] },
                }}
                disableColumnResize
                disableRowSelectionOnClick
                onRowClick={(params) => onOpenTag(params.row.path)}
                sx={{ flex: 1, minHeight: 300, "& .MuiDataGrid-row": { cursor: "pointer" } }}
            />

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
