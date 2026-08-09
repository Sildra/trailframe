import { useEffect, useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, Box, IconButton, Typography } from "@mui/material";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import DeleteIcon from "@mui/icons-material/Delete";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import { formatDateTime } from "../lib/format";

type Activity = components["schemas"]["ActivitySummary"];

interface ActivityListProps {
    onSelect: (activity: Activity) => void;
    showDelete?: boolean;
}

function formatDistance(meters: number | null | undefined): string {
    return `${((meters ?? 0) / 1000).toFixed(1)} km`;
}

function formatDuration(seconds: number | null | undefined): string {
    return `${((seconds ?? 0) / 3600).toFixed(1)} h`;
}

function formatDate(iso: string | null | undefined): string {
    if (!iso) {
        return "-";
    }

    return formatDateTime(iso);
}

function formatType(activity: Activity): string {
    if (activity.activity_type) {
        return activity.activity_type;
    }

    if (activity.activity_id?.startsWith("Garmin:")) {
        return "Garmin";
    }

    if (activity.activity_id?.startsWith("GPX:")) {
        return "GPX";
    }

    return "-";
}

export default function ActivityList({ onSelect, showDelete = false }: ActivityListProps) {
    const [activities, setActivities] = useState<Activity[]>([]);
    const [busyId, setBusyId] = useState<number | null>(null);
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [pendingDelete, setPendingDelete] = useState<Activity | null>(null);

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/activities")
            .then(({ data, error }) => {
                if (!cancelled && !error && data) {
                    setActivities(data);
                }
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, []);

    async function deleteActivity(id: number) {
        setBusyId(id);

        const { error } = await api.DELETE("/api/activities/{activity_id}", {
            params: { path: { activity_id: id } },
        });

        setBusyId(null);

        if (!error) {
            setActivities((prev) => prev.filter((a) => a.id !== id));
        }
    }

    function confirmDelete() {
        setConfirmOpen(false);

        if (pendingDelete?.id != null) {
            deleteActivity(pendingDelete.id);
        }

        setPendingDelete(null);
    }

    const columns: GridColDef<Activity>[] = [
        { field: "name", headerName: "Activity", flex: 1, valueGetter: (_value, row) => row.name ?? row.activity_id ?? "-" },
        { field: "activity_type", headerName: "Type", width: 120, valueGetter: (_value, row) => formatType(row) },
        { field: "start_time", headerName: "Date", width: 180, valueGetter: (_value, row) => row.start_time ?? "", valueFormatter: (value) => formatDate(value) },
        { field: "distance", headerName: "Distance", width: 120, type: "number", valueGetter: (_value, row) => row.distance ?? 0, valueFormatter: (value) => formatDistance(value) },
        { field: "duration", headerName: "Duration", width: 120, type: "number", valueGetter: (_value, row) => row.duration ?? 0, valueFormatter: (value) => formatDuration(value) },
        { field: "photos", headerName: "Photos", width: 80, type: "number", valueGetter: (_value, row) => row.photos ?? 0 },
    ];

    if (showDelete) {
        columns.push({
            field: "actions",
            headerName: "",
            width: 48,
            sortable: false,
            filterable: false,
            disableColumnMenu: true,
            renderCell: (params) => (
                params.row.id != null && (
                    <IconButton
                        size="small"
                        color="error"
                        disabled={busyId !== null}
                        onClick={(event) => {
                            event.stopPropagation();
                            setPendingDelete(params.row);
                            setConfirmOpen(true);
                        }}
                    >
                        <DeleteIcon fontSize="small" />
                    </IconButton>
                )
            ),
        });
    }

    if (activities.length === 0) {
        return <Typography color="text.secondary">No activities yet.</Typography>;
    }

    return (
        <Box sx={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
            <DataGrid
                rows={activities}
                columns={columns}
                initialState={{
                    sorting: { sortModel: [{ field: "start_time", sort: "desc" }] },
                }}
                disableColumnFilter={false}
                disableRowSelectionOnClick
                disableColumnResize
                hideFooter
                onRowClick={(_params) => onSelect(_params.row)}
                sx={{ flex: 1, minHeight: 300, "& .MuiDataGrid-row": { cursor: "pointer" } }}
            />
            <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
                <DialogTitle>Delete activity</DialogTitle>
                <DialogContent>
                    <Typography>
                        Are you sure you want to delete &ldquo;{pendingDelete?.name ?? pendingDelete?.activity_id}&rdquo;?
                    </Typography>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setConfirmOpen(false)}>Cancel</Button>
                    <Button color="error" onClick={confirmDelete}>Delete</Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
}
