import { useState } from "react";
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    IconButton,
    TextField,
    Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import { groupKey } from "../lib/groups";
import ThumbnailGallery from "./ThumbnailGallery";

type PhotoGroupSummary = components["schemas"]["PhotoGroupSummary"];

function formatDate(date: Date): string {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");

    return `${year}-${month}-${day}`;
}

interface GroupedGalleryProps {
    groups: PhotoGroupSummary[] | null;
    collapsed: Set<string>;
    selectedPhotoId: number | null;
    favorites?: Set<number>;
    onSelect: (photoId: number) => void;
    onToggle: (key: string) => void;
    onRefresh: () => Promise<void>;
}

export default function GroupedGallery({
    groups,
    collapsed,
    selectedPhotoId,
    favorites,
    onSelect,
    onToggle,
    onRefresh,
}: GroupedGalleryProps) {
    const [dialogOpen, setDialogOpen] = useState(false);
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [pendingDelete, setPendingDelete] = useState<PhotoGroupSummary | null>(null);
    const [name, setName] = useState("");
    const [startDate, setStartDate] = useState("");
    const [endDate, setEndDate] = useState("");

    if (groups === null) {
        return null;
    }

    const openDialog = async () => {
        setDialogOpen(true);

        if (selectedPhotoId === null || selectedPhotoId === undefined) {
            return;
        }

        const { data, error } = await api.GET("/api/photos/{photo_id}/data", {
            params: { path: { photo_id: selectedPhotoId } },
        });

        if (error || !data?.date) {
            return;
        }

        const start = data.date.slice(0, 10);
        const end = new Date(`${start}T00:00:00`);
        end.setDate(end.getDate() + 7);

        setStartDate(start);
        setEndDate(formatDate(end));
    };

    const onCreate = async (event: React.FormEvent) => {
        event.preventDefault();

        if (!name.trim() || !startDate || !endDate) {
            return;
        }

        const { error } = await api.POST("/api/photos/groups", {
            body: { name: name.trim(), start_date: startDate, end_date: endDate },
        });

        if (error) {
            return;
        }

        setName("");
        setStartDate("");
        setEndDate("");
        setDialogOpen(false);
        await onRefresh();
    };

    const onDelete = async (group: PhotoGroupSummary) => {
        if (group.id === null || group.id === undefined) {
            return;
        }

        const { error } = await api.DELETE("/api/photos/groups/{group_id}", {
            params: { path: { group_id: group.id } },
        });

        if (error) {
            return;
        }

        await onRefresh();
    };

    const confirmDelete = async () => {
        setConfirmOpen(false);

        if (pendingDelete) {
            await onDelete(pendingDelete);
            setPendingDelete(null);
        }
    };

    return (
        <>
            <Button
                variant="outlined"
                size="small"
                color="success"
                startIcon={<AddIcon />}
                onClick={openDialog}
                sx={{ m: 1 }}
            >
                Add group
            </Button>

            <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)}>
                <DialogTitle>New group</DialogTitle>
                <form onSubmit={onCreate}>
                    <DialogContent>
                        <TextField
                            label="Name"
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                            fullWidth
                            margin="dense"
                        />
                        <TextField
                            label="Start date"
                            type="date"
                            value={startDate}
                            onChange={(event) => setStartDate(event.target.value)}
                            fullWidth
                            margin="dense"
                            slotProps={{ inputLabel: { shrink: true } }}
                        />
                        <TextField
                            label="End date"
                            type="date"
                            value={endDate}
                            onChange={(event) => setEndDate(event.target.value)}
                            fullWidth
                            margin="dense"
                            slotProps={{ inputLabel: { shrink: true } }}
                        />
                    </DialogContent>
                    <DialogActions>
                        <Button type="button" onClick={() => setDialogOpen(false)}>
                            Cancel
                        </Button>
                        <Button type="submit">Create</Button>
                    </DialogActions>
                </form>
            </Dialog>

            <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
                <DialogTitle>Delete group</DialogTitle>
                <DialogContent>
                    <Typography>Are you sure you want to delete &ldquo;{pendingDelete?.name}&rdquo;?</Typography>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setConfirmOpen(false)}>Cancel</Button>
                    <Button color="error" onClick={confirmDelete}>Delete</Button>
                </DialogActions>
            </Dialog>

            {groups.map((group) => {
                const key = groupKey(group);
                const isCollapsed = collapsed.has(key);
                const photoCount = group.photo_ids?.length ?? 0;

                return (
                    <Accordion
                        key={key}
                        expanded={!isCollapsed}
                        onChange={() => onToggle(key)}
                        disableGutters
                        sx={{
                            "&::before": { display: "none" },
                            boxShadow: "none",
                            borderTop: 1,
                            borderColor: "divider",
                        }}
                    >
                        <AccordionSummary
                            expandIcon={<ExpandMoreIcon />}
                            sx={{
                                "&:hover": { bgcolor: "action.hover" },
                                "& .MuiAccordionSummary-content": { alignItems: "center", gap: 1 },
                            }}
                        >
                            <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                {group.name} ({photoCount})
                            </Typography>
                            {!group.automatic && group.id !== null && group.id !== undefined && (
                                <IconButton
                                    size="small"
                                    color="error"
                                    sx={{ ml: "auto" }}
                                    onClick={(event) => {
                                        event.stopPropagation();
                                        setPendingDelete(group);
                                        setConfirmOpen(true);
                                    }}
                                >
                                    <DeleteIcon fontSize="small" />
                                </IconButton>
                            )}
                        </AccordionSummary>
                        <AccordionDetails sx={{ p: 0 }}>
                            <ThumbnailGallery
                                photoIds={group.photo_ids ?? []}
                                selectedPhotoId={selectedPhotoId}
                                favorites={favorites}
                                onSelect={onSelect}
                            />
                        </AccordionDetails>
                    </Accordion>
                );
            })}
        </>
    );
}
