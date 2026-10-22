import { useEffect, useMemo, useState } from "react";
import {
    Box,
    Button,
    Chip,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import { api } from "../api/client";
import TagTree from "./TagTree";
import { normalizeTagPath, type TagNode } from "../lib/tags";

export interface TagPickerProps {
    open: boolean;
    /** The paths currently selected. */
    value: string[];
    onClose: () => void;
    /** Called with the whole selection when the user applies their changes. */
    onApply: (paths: string[]) => void;
    title?: string;
    /** Allow typing a path that is not in the vocabulary yet. */
    allowCreate?: boolean;
}

function TagPickerBody({ value, onClose, onApply, title, allowCreate }: Omit<TagPickerProps, "open">) {
    const [tree, setTree] = useState<TagNode[]>([]);
    const [selected, setSelected] = useState<string[]>(value);
    const [filter, setFilter] = useState("");
    const [newPath, setNewPath] = useState("");

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/tags")
            .then(({ data, error }) => {
                if (cancelled || error || !data) {
                    return;
                }
                setTree(data);
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, []);

    const known = useMemo(() => {
        const paths = new Set<string>();

        const walk = (nodes: TagNode[]) => {
            for (const node of nodes) {
                paths.add(node.path);
                walk(node.children ?? []);
            }
        };

        walk(tree);

        return paths;
    }, [tree]);

    const toggle = (path: string, checked: boolean) => {
        setSelected((previous) => {
            if (checked) {
                return previous.includes(path) ? previous : [...previous, path];
            }

            return previous.filter((entry) => entry !== path);
        });
    };

    const addNew = () => {
        const path = normalizeTagPath(newPath);

        if (!path) {
            return;
        }

        setSelected((previous) => (previous.includes(path) ? previous : [...previous, path]));
        setNewPath("");
    };

    const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
        if (event.key === "Enter") {
            event.preventDefault();
            addNew();
        }
    };

    return (
        <>
            <DialogTitle>{title}</DialogTitle>
            <DialogContent>
                <Stack spacing={1.5}>
                    <TextField
                        label="Search"
                        size="small"
                        value={filter}
                        onChange={(event) => setFilter(event.target.value)}
                        placeholder="Filter the vocabulary"
                    />
                    <Box sx={{ maxHeight: 320, overflowY: "auto", border: 1, borderColor: "divider", borderRadius: 1 }}>
                        <TagTree
                            nodes={tree}
                            checkedPaths={selected}
                            checkable
                            onToggleCheck={toggle}
                            filter={filter}
                            emptyLabel="No tags in the vocabulary yet."
                        />
                    </Box>
                    {selected.length > 0 && (
                        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                            {selected.map((path) => (
                                <Chip key={path} size="small" label={path} onDelete={() => toggle(path, false)} />
                            ))}
                        </Box>
                    )}
                    {allowCreate && (
                        <TextField
                            label="New tag path"
                            size="small"
                            value={newPath}
                            onChange={(event) => setNewPath(event.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="e.g. Landscape/Hill"
                            helperText="Type a full path and press Enter. Missing parents are created automatically."
                        />
                    )}
                    {allowCreate && newPath.trim().length > 0 && !known.has(normalizeTagPath(newPath)) && (
                        <Typography variant="caption" color="text.secondary">
                            &ldquo;{normalizeTagPath(newPath)}&rdquo; is not in the vocabulary yet — it will be created.
                        </Typography>
                    )}
                </Stack>
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose}>Cancel</Button>
                <Button variant="contained" onClick={() => onApply(selected)}>
                    Apply
                </Button>
            </DialogActions>
        </>
    );
}

export default function TagPicker({ open, value, onClose, onApply, title = "Select tags", allowCreate = true }: TagPickerProps) {
    return (
        <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
            {open && (
                <TagPickerBody
                    value={value}
                    onClose={onClose}
                    onApply={onApply}
                    title={title}
                    allowCreate={allowCreate}
                />
            )}
        </Dialog>
    );
}
