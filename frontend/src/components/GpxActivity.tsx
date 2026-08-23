import { useEffect, useRef, useState } from "react";
import { Box, Button, Typography } from "@mui/material";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import { formatDateTime } from "../lib/format";
import { useEvents } from "../events/EventContext";

type GpxActivity = components["schemas"]["GpxActivitySummary"];

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

export default function GpxActivity() {
    const inputRef = useRef<HTMLInputElement | null>(null);
    const [busy, setBusy] = useState(false);
    const [activities, setActivities] = useState<GpxActivity[]>([]);
    const { pushText } = useEvents();

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/activities/gpx")
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
        const { data, error } = await api.GET("/api/activities/gpx");

        if (!error && data) {
            setActivities(data);
        }
    }

    async function importActivity(gpxId: number) {
        api.POST("/api/activities/gpx/import/{gpx_id}", {
            params: { path: { gpx_id: gpxId } },
        }).then(({ data, error }) => {
            if (error || !data) {
                pushText("Failed to import activity", "error");
                return;
            }
            pushText(`Activity "${data.name ?? data.activity_id}" imported`);
        });
    }

    async function onFileChange(event: React.ChangeEvent<HTMLInputElement>) {
        const files = Array.from(event.target.files ?? []);

        if (files.length === 0) {
            return;
        }

        setBusy(true);

        let uploaded = 0;
        let failed = false;

        for (const file of files) {
            const formData = new FormData();
            formData.append("file", file);

            const response = await fetch("/api/activities/gpx/upload", {
                method: "POST",
                body: formData,
            });

            if (response.ok) {
                uploaded++;
            } else {
                failed = true;
            }
        }

        setBusy(false);

        if (failed) {
            pushText(`GPX upload failed (${uploaded}/${files.length})`, "error");
        } else {
            pushText(`Uploaded ${uploaded} GPX file${uploaded === 1 ? "" : "s"}`);
        }

        event.target.value = "";

        await refresh();
    }

    const columns: GridColDef<GpxActivity>[] = [
        { field: "name", headerName: "Activity", flex: 1, valueGetter: (_value, row) => row.name ?? row.filename ?? "-" },
        { field: "start_time", headerName: "Date", width: 180, valueGetter: (_value, row) => row.start_time ?? "", valueFormatter: (value) => formatDate(value) },
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
                params.row.id != null && (
                    <Button
                        size="small"
                        variant="outlined"
                        onClick={(event) => {
                            event.stopPropagation();
                            importActivity(params.row.id as number);
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
            <input
                ref={inputRef}
                type="file"
                accept=".gpx,application/gpx+xml"
                multiple
                style={{ display: "none" }}
                onChange={onFileChange}
            />
            <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 2, mb: 2 }}>
                <Typography variant="h6">GPX</Typography>
                <Button
                    variant="contained"
                    size="small"
                    onClick={() => inputRef.current?.click()}
                    disabled={busy}
                >
                    Import GPX
                </Button>
            </Box>
            <DataGrid
                rows={activities}
                columns={columns}
                initialState={{
                    sorting: { sortModel: [{ field: "start_time", sort: "desc" }] },
                }}
                disableRowSelectionOnClick
                disableColumnResize
                hideFooter
                sx={{ flex: 1, minHeight: 300, "& .MuiDataGrid-row": { cursor: "pointer" } }}
            />
        </Box>
    );
}
