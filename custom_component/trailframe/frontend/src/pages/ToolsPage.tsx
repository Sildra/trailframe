import { useCallback, useEffect, useRef, useState } from "react";
import {
    Box,
    Button,
    Checkbox,
    CircularProgress,
    FormControlLabel,
    Paper,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Typography,
} from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { MapContainer, CircleMarker, Pane, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "../api/client";
import SectionPage from "../components/SectionPage";
import { formatDateTime } from "../lib/format";
import type { components } from "../api/generated/schema";

type ScannerStatSummary = components["schemas"]["ScannerStatSummary"];
type StorageStats = components["schemas"]["StorageStats"];
type ProcessStats = components["schemas"]["ProcessStats"];
type MapData = components["schemas"]["MapData"];
type PhotoPoint = components["schemas"]["PhotoPoint"];
type ActivityTrace = components["schemas"]["ActivityTrace"];

const SCANNERS_SECTION = "Scanners";
const MAP_SECTION = "Map";
const STATS_SECTION = "Statistics";

function formatLabel(name: string): string {
    return name.replace(/_/g, " ").replace(/^\w/, (char) => char.toUpperCase());
}

function formatThroughput(value: number): string {
    return `${value.toFixed(1)}/s`;
}

function formatBytes(size: number): string {
    if (size < 1024) {
        return `${size} B`;
    }

    const units = ["KB", "MB", "GB", "TB"];
    let value = size;
    let unit = -1;

    do {
        value /= 1024;
        unit += 1;
    } while (value >= 1024 && unit < units.length - 1);

    return `${value.toFixed(1)} ${units[unit]}`;
}

function StatisticsPane() {
    const [stats, setStats] = useState<ScannerStatSummary[] | null>(null);
    const [storage, setStorage] = useState<StorageStats | null>(null);
    const [process, setProcess] = useState<ProcessStats | null>(null);

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/statistics/scanners")
            .then(({ data, error }) => {
                if (!cancelled && !error && data) {
                    setStats(data);
                }
            })
            .catch(() => {});

        api.GET("/api/statistics/storage")
            .then(({ data, error }) => {
                if (!cancelled && !error && data) {
                    setStorage(data);
                }
            })
            .catch(() => {});

        api.GET("/api/statistics/process")
            .then(({ data, error }) => {
                if (!cancelled && !error && data) {
                    setProcess(data);
                }
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, []);

    if (stats === null || storage === null) {
        return null;
    }

    return (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
            <TableContainer>
                <Table size="small">
                    <TableHead>
                        <TableRow>
                            <TableCell>Name</TableCell>
                            <TableCell>Items</TableCell>
                            <TableCell>Value</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        <TableRow sx={{ bgcolor: "action.hover" }}>
                            <TableCell colSpan={3} sx={{ fontWeight: 600, color: "text.secondary" }}>
                                Scanner
                            </TableCell>
                        </TableRow>
                        {stats.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={3}>No scanner runs recorded yet.</TableCell>
                            </TableRow>
                        ) : (
                            stats.map((stat) => (
                                <TableRow key={stat.name}>
                                    <TableCell>{stat.name}</TableCell>
                                    <TableCell>{stat.items}</TableCell>
                                    <TableCell>{formatThroughput(stat.value)}</TableCell>
                                </TableRow>
                            ))
                        )}
                        <TableRow sx={{ bgcolor: "action.hover" }}>
                            <TableCell colSpan={3} sx={{ fontWeight: 600, color: "text.secondary" }}>
                                Filesystem
                            </TableCell>
                        </TableRow>
                        {[...storage.filesystem, { name: "database", size: storage.database_size }]
                            .sort((a, b) => b.size - a.size)
                            .map((folder) => (
                                <TableRow key={folder.name}>
                                    <TableCell>{folder.name}</TableCell>
                                    <TableCell>-</TableCell>
                                    <TableCell>{formatBytes(folder.size)}</TableCell>
                                </TableRow>
                            ))}
                        <TableRow sx={{ bgcolor: "action.hover" }}>
                            <TableCell colSpan={3} sx={{ fontWeight: 600, color: "text.secondary" }}>
                                Process
                            </TableCell>
                        </TableRow>
                        {process && (
                            <>
                                <TableRow>
                                    <TableCell>RSS</TableCell>
                                    <TableCell>-</TableCell>
                                    <TableCell>{formatBytes(process.rss)}</TableCell>
                                </TableRow>
                                <TableRow>
                                    <TableCell>VMS</TableCell>
                                    <TableCell>-</TableCell>
                                    <TableCell>{formatBytes(process.vms)}</TableCell>
                                </TableRow>
                            </>
                        )}
                    </TableBody>
                </Table>
            </TableContainer>
        </Box>
    );
}

function ScannersPane() {
    const [scanners, setScanners] = useState<string[]>([]);
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [running, setRunning] = useState(false);
    const [result, setResult] = useState<string | null>(null);

    useEffect(() => {
        api.GET("/api/pipeline/scanners")
            .then(({ data, error }) => {
                if (!error && data) {
                    setScanners(data);
                    setSelected(new Set(data));
                }
            })
            .catch(() => {});
    }, []);

    const toggle = useCallback((name: string) => {
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(name)) next.delete(name);
            else next.add(name);
            return next;
        });
    }, []);

    const selectAll = useCallback(() => setSelected(new Set(scanners)), [scanners]);
    const selectNone = useCallback(() => setSelected(new Set()), []);

    const handleRun = useCallback(() => {
        setRunning(true);
        setResult(null);

        api.POST("/api/pipeline/scan", {
            body: { scanners: [...selected] },
        })
            .then(({ error }) => {
                setResult(error ? "Error: scan could not be started" : "Scan started");
            })
            .catch(() => {
                setResult("Error: request failed");
            })
            .finally(() => {
                setRunning(false);
            });
    }, [selected]);

    return (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <Typography variant="h6">Select scanners to restart</Typography>
                <Box sx={{ display: "flex", gap: 1 }}>
                    <Button size="small" onClick={selectAll}>
                        Select all
                    </Button>
                    <Button size="small" onClick={selectNone}>
                        Select none
                    </Button>
                </Box>
            </Box>

            <Box sx={{ display: "flex", flexDirection: "column" }}>
                {scanners.map((name) => (
                    <FormControlLabel
                        key={name}
                        control={<Checkbox checked={selected.has(name)} onChange={() => toggle(name)} />}
                        label={formatLabel(name)}
                    />
                ))}
            </Box>

            <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
                <Button
                    variant="contained"
                    startIcon={running ? <CircularProgress size={18} /> : <PlayArrowIcon />}
                    disabled={running || selected.size === 0}
                    onClick={handleRun}
                >
                    Run
                </Button>
                {result !== null && (
                    <Typography variant="body2" color={result.startsWith("Error") ? "error" : "success"}>
                        {result}
                    </Typography>
                )}
            </Box>
        </Box>
    );
}

function FitBounds({ photos, activities }: { photos: PhotoPoint[]; activities: ActivityTrace[] }) {
    const map = useMap();
    const fitted = useRef(false);

    useEffect(() => {
        if (fitted.current) return;

        const bounds: L.LatLngExpression[] = [];

        for (const p of photos) bounds.push([p.lat, p.lon]);
        for (const a of activities) {
            for (const pt of a.trace) bounds.push([pt[0], pt[1]]);
        }

        if (bounds.length > 0) {
            fitted.current = true;
            map.fitBounds(bounds as L.LatLngBoundsExpression, { padding: [20, 20] });
        }
    }, [map, photos, activities]);

    return null;
}

function MapPane() {
    const [data, setData] = useState<MapData | null>(null);
    const [showPhotos, setShowPhotos] = useState(true);
    const [showActivities, setShowActivities] = useState(true);
    const [selectedPhoto, setSelectedPhoto] = useState<PhotoPoint | null>(null);
    const [selectedActivityId, setSelectedActivityId] = useState<number | null>(null);

    useEffect(() => {
        api.GET("/api/map-data")
            .then(({ data, error }) => {
                if (!error && data) {
                    setData(data);
                }
            })
            .catch(() => {});
    }, []);

    if (data === null) {
        return <CircularProgress />;
    }

    const center: L.LatLngExpression = [20, 0];

    return (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1, flex: 1, minHeight: 0 }}>
            <Box sx={{ flex: 1, minHeight: 0, borderRadius: 1, overflow: "hidden", border: 1, borderColor: "divider", position: "relative" }}>
                <MapContainer center={center} zoom={2} style={{ height: "100%", width: "100%" }}>
                    <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="/api/tiles/{z}/{x}/{y}.png" />
                    <FitBounds photos={showPhotos ? data.photos : []} activities={showActivities ? data.activities : []} />
                    <Pane name="photos" style={{ zIndex: 400 }}>
                        {showPhotos &&
                            data.photos.map((p) => (
                                <CircleMarker
                                    key={p.id}
                                    center={[p.lat, p.lon]}
                                    radius={5}
                                    pathOptions={{ color: "#e53935", fillColor: "#e53935", fillOpacity: 0.8 }}
                                    eventHandlers={{ click: () => setSelectedPhoto(p) }}
                                />
                            ))}
                    </Pane>
                    <Pane name="activities" style={{ zIndex: 500 }}>
                        {showActivities &&
                            data.activities.map((a) => {
                                const selected = a.id === selectedActivityId;

                                return (
                                    <Polyline
                                        key={a.id}
                                        positions={a.trace as L.LatLngExpression[]}
                                        pathOptions={{
                                            color: selected ? "#f57c00" : "#1976d2",
                                            weight: selected ? 4 : 2,
                                        }}
                                        eventHandlers={{
                                            click: () => setSelectedActivityId(selected ? null : a.id),
                                        }}
                                    >
                                        <Popup>
                                            <Box sx={{ fontSize: 13 }}>
                                                <Box sx={{ fontWeight: 600, mb: 0.5 }}>{a.name ?? `Activity ${a.id}`}</Box>
                                                {a.start_time && (
                                                    <Box sx={{ color: "text.secondary" }}>{formatDateTime(a.start_time)}</Box>
                                                )}
                                                {(a.distance != null || a.duration != null) && (
                                                    <Box>
                                                        {[
                                                            a.distance != null ? `${(a.distance / 1000).toFixed(1)} km` : null,
                                                            a.duration != null ? `${(a.duration / 3600).toFixed(1)} h` : null,
                                                        ]
                                                            .filter(Boolean)
                                                            .join(" · ")}
                                                    </Box>
                                                )}
                                            </Box>
                                        </Popup>
                                    </Polyline>
                                );
                            })}
                    </Pane>
                </MapContainer>
                {selectedPhoto && (
                    <Box
                        onClick={() => setSelectedPhoto(null)}
                        sx={{
                            position: "absolute",
                            top: 0,
                            left: 0,
                            right: 0,
                            bottom: 0,
                            zIndex: 1000,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            cursor: "pointer",
                        }}
                    >
                        <img
                            src={`/api/photos/${selectedPhoto.id}/thumbnail?size=400`}
                            alt=""
                            style={{ width: 400, height: "auto", borderRadius: 4, boxShadow: "0 4px 20px rgba(0,0,0,0.5)" }}
                        />
                    </Box>
                )}
                <Paper elevation={3} sx={{ position: "absolute", bottom: 12, right: 12, zIndex: 1000, px: 1, py: 0.5, display: "flex", flexDirection: "column" }}>
                    <FormControlLabel
                        control={<Checkbox checked={showPhotos} onChange={(e) => setShowPhotos(e.target.checked)} size="small" />}
                        label={<Typography variant="caption">Photos ({data.photos.length})</Typography>}
                    />
                    <FormControlLabel
                        control={<Checkbox checked={showActivities} onChange={(e) => setShowActivities(e.target.checked)} size="small" />}
                        label={<Typography variant="caption">Activities ({data.activities.length})</Typography>}
                    />
                </Paper>
            </Box>
        </Box>
    );
}

const SECTIONS = [
    { id: MAP_SECTION, label: MAP_SECTION },
    { id: SCANNERS_SECTION, label: SCANNERS_SECTION },
    { id: STATS_SECTION, label: STATS_SECTION },
];

export default function ToolsPage() {
    const [selected, setSelected] = useState(MAP_SECTION);

    return (
        <SectionPage title="Tools" sections={SECTIONS} selected={selected} onSelect={setSelected}>
            {selected === SCANNERS_SECTION ? <ScannersPane /> : selected === MAP_SECTION ? <MapPane /> : <StatisticsPane />}
        </SectionPage>
    );
}
