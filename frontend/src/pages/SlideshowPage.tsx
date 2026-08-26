import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Box, Button, CircularProgress, IconButton, Typography } from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import PauseIcon from "@mui/icons-material/Pause";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import WireframeMap from "../components/WireframeMap";
import { formatDateTime } from "../lib/format";
import { project } from "../lib/projection";

type ActivitySummary = components["schemas"]["ActivitySummary"];
type Activity = components["schemas"]["Activity"];
type Photo = components["schemas"]["PhotoDetail"];

const SLIDE_INTERVAL_MS = 5000;
const PROGRESS_TICK_MS = 100;

export type SlideshowSource =
    | { kind: "activity"; activity: ActivitySummary }
    | { kind: "group"; name: string; photoIds: number[]; thumbnails?: boolean };

function slideImageUrl(photoId: number, size?: number | null): string {
    return size ? `./api/photos/${photoId}/thumbnail?size=${size}` : `./api/photos/${photoId}/image`;
}

interface SlideshowPageProps {
    source: SlideshowSource;
    onExit: () => void;
}

type Slide = { kind: "map" } | { kind: "photo"; photoId: number };

interface MapData {
    map: {
        width: number;
        height: number;
        zoom: number;
        center: { lat: number; lon: number };
        bounds: { min_lat: number; min_lon: number; max_lat: number; max_lon: number };
    };
    trace: {
        points: Array<[number, number]>;
        start: [number, number] | null;
        end: [number, number] | null;
    };
}

function computeView(map: MapData["map"], trace: MapData["trace"]): { x: number; y: number; size: number } | null {
    if (!trace.points || trace.points.length < 2) {
        return null;
    }

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    for (const [x, y] of trace.points) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
    }

    const extent = Math.max(maxX - minX, maxY - minY);

    if (extent <= 0) {
        return null;
    }

    const size = Math.min(extent * 1.15, map.width);
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;

    return {
        x: Math.min(Math.max(centerX - size / 2, 0), map.width - size),
        y: Math.min(Math.max(centerY - size / 2, 0), map.height - size),
        size,
    };
}

function Pin({ x, y, color, glyph }: { x: number; y: number; color: string; glyph: string }) {
    return (
        <g transform={`translate(${x},${y})`}>
            <path
                d="M0,0 C-8,-12 -16,-20 -16,-30 A16,16 0 1,1 16,-30 C16,-20 8,-12 0,0 Z"
                fill={color}
                stroke="#ffffff"
                strokeWidth={3}
            />
            <text
                x={0}
                y={-27}
                fill="#ffffff"
                fontFamily="Arial, sans-serif"
                fontSize={15}
                textAnchor="middle"
            >
                {glyph}
            </text>
        </g>
    );
}

const TRACE_STROKE = "#e53935";
const START_COLOR = "#2e7d32";
const STOP_COLOR = "#d32f2f";
const DOT_FILL = "#ffb300";
const PIN_PATH = "M0,0 C-8,-12 -16,-20 -16,-30 A16,16 0 1,1 16,-30 C16,-20 8,-12 0,0 Z";

function drawPin(ctx: CanvasRenderingContext2D, x: number, y: number, color: string, glyph: string) {
    ctx.save();
    ctx.translate(x, y);
    ctx.fillStyle = color;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 3;
    ctx.fill(new Path2D(PIN_PATH));
    ctx.stroke(new Path2D(PIN_PATH));
    ctx.fillStyle = "#ffffff";
    ctx.font = "15px Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(glyph, 0, -27);
    ctx.restore();
}

function drawMapOverlay(
    ctx: CanvasRenderingContext2D,
    mapData: MapData | null,
    photoDots: Array<[number, number]>,
) {
    if (!mapData) {
        return;
    }

    const trace = mapData.trace;

    if (trace.points.length > 1) {
        ctx.beginPath();
        trace.points.forEach(([x, y], index) => (index === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
        ctx.strokeStyle = TRACE_STROKE;
        ctx.lineWidth = 8;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.stroke();
    }

    if (trace.start) {
        drawPin(ctx, trace.start[0], trace.start[1], START_COLOR, "▶");
    }

    if (trace.end) {
        drawPin(ctx, trace.end[0], trace.end[1], STOP_COLOR, "■");
    }

    ctx.beginPath();

    for (const [x, y] of photoDots) {
        ctx.moveTo(x + 10, y);
        ctx.arc(x, y, 10, 0, 2 * Math.PI);
    }

    ctx.fillStyle = DOT_FILL;
    ctx.fill();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.stroke();
}

interface MapContentProps {
    box: number;
    mapUrl: string;
    mapData: MapData | null;
    photoDots: Array<[number, number]>;
    onError: () => void;
}

function MapContent({ box, mapUrl, mapData, photoDots, onError }: MapContentProps) {
    const mapWidth = mapData?.map.width ?? 1500;
    const mapHeight = mapData?.map.height ?? 1500;
    const view = mapData ? computeView(mapData.map, mapData.trace) : null;

    const viewSize = view?.size ?? mapWidth;
    const scale = box > 0 ? box / viewSize : 1;
    const offsetX = view ? -view.x * scale : 0;
    const offsetY = view ? -view.y * scale : 0;
    const viewBox = view ? `${view.x} ${view.y} ${view.size} ${view.size}` : `0 0 ${mapWidth} ${mapHeight}`;
    const dotRadius = 10 / scale;

    return (
        <Box sx={{ position: "relative", flexShrink: 0, overflow: "hidden", width: box, height: box }}>
            <img
                src={mapUrl}
                alt="Activity map"
                onError={onError}
                style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    display: "block",
                    maxWidth: "none",
                    width: mapWidth * scale,
                    height: mapHeight * scale,
                    transform: `translate(${offsetX}px, ${offsetY}px)`,
                }}
            />
            {mapData && (
                <svg viewBox={viewBox} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", display: "block" }}>
                    {mapData.trace.points.length > 1 && (
                        <polyline
                            points={mapData.trace.points.map(([x, y]) => `${x},${y}`).join(" ")}
                            fill="none"
                            stroke="#e53935"
                            strokeWidth={8}
                            strokeLinecap="round"
                            strokeLinejoin="round"
                        />
                    )}
                    {mapData.trace.start && (
                        <Pin x={mapData.trace.start[0]} y={mapData.trace.start[1]} color="#2e7d32" glyph="▶" />
                    )}
                    {mapData.trace.end && (
                        <Pin x={mapData.trace.end[0]} y={mapData.trace.end[1]} color="#d32f2f" glyph="■" />
                    )}
                    {photoDots.map(([x, y], index) => (
                        <circle
                            key={index}
                            cx={x}
                            cy={y}
                            r={dotRadius}
                            fill="#ffb300"
                            stroke="#ffffff"
                            strokeWidth={Math.max(2, 3 / scale)}
                        />
                    ))}
                </svg>
            )}
        </Box>
    );
}

export default function SlideshowPage({ source, onExit }: SlideshowPageProps) {
    const activity = source.kind === "activity" ? source.activity : null;
    const stageRef = useRef<HTMLDivElement | null>(null);
    const stageBoxRef = useRef(0);
    const [stageBox, setStageBox] = useState(0);
    const [fetchedPhotos, setFetchedPhotos] = useState<Photo[]>([]);
    const [slideIndex, setSlideIndex] = useState(0);
    const [imageSize, setImageSize] = useState<number | null>(null);
    const [paused, setPaused] = useState(false);
    const [progress, setProgress] = useState(0);
    const progressRef = useRef(0);
    const [exporting, setExporting] = useState(false);
    const [mapFailed, setMapFailed] = useState(false);
    const [detail, setDetail] = useState<Activity | null>(null);

    const photos = fetchedPhotos;
    const thumbnails = source.kind === "group" ? source.thumbnails : false;

    const mapData = useMemo<MapData | null>(() => {
        if (!detail?.map_data || typeof detail.map_data !== "object") {
            return null;
        }

        return detail.map_data as unknown as MapData;
    }, [detail]);

    const photoDots = useMemo<Array<[number, number]>>(() => {
        if (!mapData) {
            return [];
        }

        const dots: Array<[number, number]> = [];

        for (const photo of photos) {
            if (photo.latitude == null || photo.longitude == null) {
                continue;
            }

            dots.push(project(photo.latitude, photo.longitude, mapData.map));
        }

        return dots;
    }, [mapData, photos]);

    const slides = useMemo<Slide[]>(() => {
        const list: Slide[] = [];

        if (source.kind === "activity" && !mapFailed) {
            list.push({ kind: "map" });
        }

        const photoIds =
            source.kind === "group"
                ? source.photoIds
                : photos.map((photo) => photo.id).filter((id): id is number => id != null);

        for (const photoId of photoIds) {
            list.push({ kind: "photo", photoId });
        }

        return list;
    }, [photos, mapFailed, source]);

    useEffect(() => {
        const node = stageRef.current;

        if (!node) {
            return;
        }

        const update = () => {
            const box = Math.min(node.clientWidth, node.clientHeight);
            stageBoxRef.current = box;
            setStageBox(box);
        };

        update();

        const observer = new ResizeObserver(update);
        observer.observe(node);

        return () => observer.disconnect();
    }, [activity]);

    useEffect(() => {
        const box = stageBoxRef.current;

        setImageSize(thumbnails && box > 0 ? Math.round(box * (window.devicePixelRatio || 1)) : null);
        // size is intentionally recomputed only when the next image is fetched, not on resize
    }, [slideIndex, thumbnails]);

    useEffect(() => {
        if (!activity?.id) {
            return;
        }

        let cancelled = false;

        api.GET("/api/activities/{activity_id}", {
            params: { path: { activity_id: activity.id } },
        })
            .then(({ data, error }) => {
                if (!cancelled && !error && data) {
                    setDetail(data);
                }
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, [activity]);

    useEffect(() => {
        let cancelled = false;

        const load = async () => {
            if (source.kind === "activity") {
                const activityId = source.activity.id;

                if (!activityId) {
                    return;
                }

                const { data, error } = await api.GET("/api/activities/{activity_id}/photos", {
                    params: { path: { activity_id: activityId } },
                });

                if (cancelled || error || !data) {
                    return;
                }

                setFetchedPhotos(data.filter((photo) => photo.id != null));
            } else {
                const { data, error } = await api.GET("/api/photos");

                if (cancelled || error || !data) {
                    return;
                }

                const ids = new Set(source.photoIds);
                setFetchedPhotos(data.filter((photo) => photo.id != null && ids.has(photo.id)));
            }
        };

        load().catch(() => {});

        return () => {
            cancelled = true;
        };
    }, [source]);

    const previous = useCallback(() => {
        progressRef.current = 0;
        setProgress(0);
        setSlideIndex((index) => (slides.length === 0 ? 0 : (index - 1 + slides.length) % slides.length));
    }, [slides.length]);

    const next = useCallback(() => {
        progressRef.current = 0;
        setProgress(0);
        setSlideIndex((index) => (slides.length === 0 ? 0 : (index + 1) % slides.length));
    }, [slides.length]);

    useEffect(() => {
        if (paused || slides.length <= 1) {
            return;
        }

        const timer = window.setInterval(() => {
            progressRef.current = Math.min(
                100,
                progressRef.current + (100 * PROGRESS_TICK_MS) / SLIDE_INTERVAL_MS,
            );
            setProgress(progressRef.current);

            if (progressRef.current >= 100) {
                progressRef.current = 0;
                setProgress(0);
                setSlideIndex((index) => (index + 1) % slides.length);
            }
        }, PROGRESS_TICK_MS);

        return () => window.clearInterval(timer);
    }, [paused, slides.length, slideIndex]);

    useEffect(() => {
        function onKeyDown(event: KeyboardEvent) {
            if (event.key === "ArrowRight") {
                next();
            } else if (event.key === "ArrowLeft") {
                previous();
            } else if (event.key === " ") {
                event.preventDefault();
                setPaused((value) => !value);
            } else if (event.key === "Escape") {
                onExit();
            }
        }

        window.addEventListener("keydown", onKeyDown);

        return () => window.removeEventListener("keydown", onKeyDown);
    }, [next, previous, onExit]);

    const slide = slides[slideIndex];

    useEffect(() => {
        if (slides.length <= 1) {
            return;
        }

        const nextIndex = (slideIndex + 1) % slides.length;
        const next = slides[nextIndex];

        if (next.kind === "photo") {
            const box = stageBoxRef.current;
            const size =
                thumbnails && box > 0 ? Math.round(box * (window.devicePixelRatio || 1)) : null;
            const img = new Image();

            img.src = slideImageUrl(next.photoId, size);
        }
    }, [slideIndex, slides, thumbnails]);
    const currentPhoto = slide.kind === "photo" ? (photos.find((photo) => photo.id === slide.photoId) ?? null) : null;
    const currentLocation = currentPhoto?.location || currentPhoto?.country || null;
    const currentDate = currentPhoto?.date ? formatDateTime(currentPhoto.date) : null;
    const title =
        source.kind === "activity" ? (activity?.name ?? activity?.activity_id ?? "Activity") : source.name;
    const activityId = source.kind === "activity" ? (activity?.id ?? null) : null;
    const activityName = source.kind === "activity" ? (activity?.name ?? null) : null;

    async function exportZip() {
        if (!activityId || exporting) {
            return;
        }

        setExporting(true);

        try {
            const mapWidth = mapData?.map.width ?? 1500;
            const mapHeight = mapData?.map.height ?? 1500;
            const canvas = document.createElement("canvas");
            canvas.width = mapWidth;
            canvas.height = mapHeight;
            const ctx = canvas.getContext("2d");
            let overlay: Blob | null = null;

            if (ctx) {
                try {
                    const mapImg = new Image();

                    await new Promise<void>((resolve, reject) => {
                        mapImg.onload = () => resolve();
                        mapImg.onerror = () => reject(new Error("map image failed to load"));
                        mapImg.src = `./api/activities/${activityId}/map`;
                    });

                    ctx.drawImage(mapImg, 0, 0, mapWidth, mapHeight);
                    drawMapOverlay(ctx, mapData, photoDots);
                    overlay = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
                } catch {
                    overlay = null;
                }
            }

            const form = new FormData();

            if (overlay) {
                form.append("overlay", overlay, "map.png");
            }

            const response = await fetch(`./api/activities/${activityId}/zip`, { method: "POST", body: form });

            if (!response.ok) {
                throw new Error(`zip export failed: ${response.status}`);
            }

            const blob = await response.blob();
            const match = /filename="([^"]+)"/.exec(response.headers.get("content-disposition") ?? "");
            const filename = match?.[1] ?? `${activityName ?? "activity"}.zip`;
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = filename;
            anchor.style.display = "none";
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            URL.revokeObjectURL(url);
        } finally {
            setExporting(false);
        }
    }

    return (
        <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
            <Box
                sx={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 2,
                    px: 1.5,
                    py: 0.5,
                    borderBottom: 1,
                    borderColor: "divider",
                }}
            >
                <Typography sx={{ fontWeight: 600 }}>{title}</Typography>
                <Typography sx={{ color: "text.secondary", fontSize: 13, fontFamily: "monospace" }}>
                    {slides.length === 0 ? "0 / 0" : `${slideIndex + 1} / ${slides.length}`}
                    {currentLocation && ` · ${currentLocation}`}
                    {currentDate && ` · ${currentDate}`}
                </Typography>
                <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                    <IconButton size="small" aria-label="Previous slide" onClick={previous}>
                        <ChevronLeftIcon fontSize="small" />
                    </IconButton>
                    <Box sx={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
                        <IconButton
                            size="small"
                            aria-label={paused ? "Play" : "Pause"}
                            aria-pressed={paused}
                            disabled={slides.length <= 1}
                            onClick={() => setPaused((value) => !value)}
                        >
                            {paused ? <PlayArrowIcon fontSize="small" /> : <PauseIcon fontSize="small" />}
                        </IconButton>
                        <CircularProgress
                            size={36}
                            thickness={1.2}
                            variant="determinate"
                            value={progress}
                            sx={{
                                position: "absolute",
                                inset: -2,
                                opacity: 0.4,
                                pointerEvents: "none",
                                "& .MuiCircularProgress-circle": { transition: "none" },
                            }}
                        />
                    </Box>
                    <IconButton size="small" aria-label="Next slide" onClick={next}>
                        <ChevronRightIcon fontSize="small" />
                    </IconButton>
                    <Button size="small" onClick={onExit}>
                        Exit
                    </Button>
                    {source.kind === "activity" && (
                        <Button size="small" onClick={exportZip} disabled={exporting}>
                            {exporting ? "Exporting…" : "Export ZIP"}
                        </Button>
                    )}
                </Box>
            </Box>
            <Box
                ref={stageRef}
                sx={{ flex: 1, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" }}
            >
                {slides.length === 0 ? (
                    <Typography color="text.secondary">
                        {source.kind === "group" ? "No photos in this group." : "No map or photos for this activity."}
                    </Typography>
                ) : slide.kind === "map" ? (
                    <MapContent
                        box={stageBox}
                        mapUrl={`./api/activities/${activityId}/map`}
                        mapData={mapData}
                        photoDots={photoDots}
                        onError={() => setMapFailed(true)}
                    />
                ) : (
                    <Box sx={{ position: "relative", width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <img
                            src={slideImageUrl(slide.photoId, thumbnails ? imageSize : null)}
                            alt={`Photo ${slide.photoId}`}
                            style={{ display: "block", width: "100%", height: "100%", objectFit: "contain" }}
                        />
                        <Box
                            sx={{
                                position: "absolute",
                                right: 16,
                                bottom: 16,
                                width: 220,
                                maxWidth: "30%",
                                bgcolor: "#ffffff",
                                border: 1,
                                borderColor: "divider",
                                borderRadius: 1,
                                boxShadow: 3,
                                overflow: "hidden",
                                pointerEvents: "none",
                            }}
                        >
                            <WireframeMap
                                photoId={slide.photoId}
                                wireframe={currentPhoto?.wireframe ?? null}
                                map={currentPhoto?.map ?? null}
                            />
                        </Box>
                    </Box>
                )}
            </Box>
        </Box>
    );
}
