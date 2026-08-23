import { useEffect, useState } from "react";
import {
    Box,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    TextField,
    Typography,
} from "@mui/material";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import { formatDateTime } from "../lib/format";
import { useEvents } from "../events/EventContext";

type GarminActivity = components["schemas"]["GarminActivitySummary"];

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

export default function GarminActivity() {
    const [open, setOpen] = useState(false);
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [busy, setBusy] = useState(false);
    const [activities, setActivities] = useState<GarminActivity[]>([]);
    const { pushText } = useEvents();

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/activities/garmin")
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

    async function refresh() {
        const { data, error } = await api.GET("/api/activities/garmin");

        if (!error && data) {
            setActivities(data);
        }
    }

    async function importActivity(activityId: number) {
        api.POST(
            "/api/activities/import/{activity_id}",
            { params: { path: { activity_id: activityId } } },
        ).then(({ data, error }) => {
            if (error || !data) {
                pushText("Failed to import activity", "error");
                return;
            }
            pushText(`Activity "${data.name ?? data.activity_id}" imported`);
        });
    }

    async function syncGarmin() {
        if (!email || !password) {
            return;
        }

        setBusy(true);

        const { data, error } = await api.POST("/api/activities/garmin/sync", {
            body: { email, password },
        });

        setBusy(false);

        if (error || !data?.success) {
            pushText("Garmin sync failed", "error");
            return;
        }

        pushText("Garmin sync started");

        setOpen(false);
        setEmail("");
        setPassword("");
        setTimeout(refresh, 10000);
    }

    const columns: GridColDef<GarminActivity>[] = [
        { field: "activityName", headerName: "Activity", flex: 1, valueGetter: (_value, row) => row.activityName ?? "-" },
        { field: "startTimeLocal", headerName: "Date", width: 180, valueGetter: (_value, row) => row.startTimeLocal ?? "", valueFormatter: (value) => formatDate(value) },
        { field: "distance", headerName: "Distance", width: 120, type: "number", valueGetter: (_value, row) => row.distance ?? 0, valueFormatter: (value) => formatDistance(value) },
        { field: "duration", headerName: "Duration", width: 120, type: "number", valueGetter: (_value, row) => row.duration ?? 0, valueFormatter: (value) => formatDuration(value) },
        { field: "photos", headerName: "Photos", width: 80, type: "number", valueGetter: (_value, row) => row.photos ?? 0 },
        {
            field: "actions",
            headerName: "",
            width: 100,
            sortable: false,
            filterable: false,
            disableColumnMenu: true,
            renderCell: (params) => (
                params.row.activityId != null && (
                    <Button
                        size="small"
                        variant="outlined"
                        onClick={(event) => {
                            event.stopPropagation();
                            importActivity(params.row.activityId as number);
                        }}
                    >
                        {params.row.imported ? "Reimport" : "Import"}
                    </Button>
                )
            ),
        },
    ];

    return (
        <Box sx={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
            <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 2, mb: 2 }}>
                <Typography variant="h6">Garmin</Typography>
                <Button variant="contained" size="small" onClick={() => setOpen(true)}>
                    Sync from Garmin
                </Button>
            </Box>
            <DataGrid
                rows={activities}
                columns={columns}
                getRowId={(row) => (row.activityId ?? row.id) as number}
                initialState={{
                    sorting: { sortModel: [{ field: "startTimeLocal", sort: "desc" }] },
                }}
                disableRowSelectionOnClick
                disableColumnResize
                hideFooter
                sx={{ flex: 1, minHeight: 300, "& .MuiDataGrid-row": { cursor: "pointer" } }}
            />
            <Dialog open={open} onClose={() => !busy && setOpen(false)}>
                <DialogTitle>Sync from Garmin</DialogTitle>
                <DialogContent>
                    <TextField
                        label="Email"
                        type="email"
                        value={email}
                        onChange={(event) => setEmail(event.target.value)}
                        disabled={busy}
                        fullWidth
                        margin="dense"
                    />
                    <TextField
                        label="Password"
                        type="password"
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        disabled={busy}
                        fullWidth
                        margin="dense"
                    />
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setOpen(false)} disabled={busy}>
                        Cancel
                    </Button>
                    <Button onClick={syncGarmin} disabled={busy}>
                        Sync
                    </Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
}
