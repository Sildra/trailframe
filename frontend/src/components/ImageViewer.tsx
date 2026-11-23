import { useCallback, useEffect, useRef, useState } from "react";
import { Box, Typography } from "@mui/material";

import {
    confidenceOpacity,
    confidenceRegions,
    dedupeObjectBoxes,
    objectRect,
    type ObjectHover,
} from "../lib/objectBoxes";
import type { TiltOverlay } from "../lib/processing";

interface ImageViewerProps {
    photoId: number | null;
    /** Bumped when the photo's files change, so the image is fetched again. */
    version?: number;
    hoveredObject?: ObjectHover | null;
    hoveredTilt?: TiltOverlay | null;
}

function computeDims(img: HTMLImageElement) {
    const cw = img.clientWidth;
    const ch = img.clientHeight;
    const nw = img.naturalWidth;
    const nh = img.naturalHeight;
    const scaleX = cw / nw;
    const scaleY = ch / nh;
    const scale = Math.min(scaleX, scaleY);
    const ox = (cw - nw * scale) / 2;
    const oy = (ch - nh * scale) / 2;

    return { cw, ch, nw, nh, scale, ox, oy };
}

export default function ImageViewer({ photoId, version = 0, hoveredObject, hoveredTilt }: ImageViewerProps) {
    const imgRef = useRef<HTMLImageElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [dims, setDims] = useState<ReturnType<typeof computeDims> | null>(null);

    const recalc = useCallback(() => {
        if (imgRef.current) {
            setDims(computeDims(imgRef.current));
        }
    }, []);

    useEffect(() => {
        const observer = new ResizeObserver(recalc);

        if (containerRef.current) {
            observer.observe(containerRef.current);
        }

        return () => observer.disconnect();
    }, [recalc, photoId, version]);

    return (
        <Box ref={containerRef} sx={{ width: "100%", height: "100%", position: "relative" }}>
            {photoId === null ? (
                <Box sx={{ display: "flex", alignItems: "center", justifyContent: "center", width: "100%", height: "100%" }}>
                    <Typography color="text.secondary">Select a photo</Typography>
                </Box>
            ) : (
                <>
                    <img
                        key={`${photoId}-${version}`}
                        ref={imgRef}
                        src={`./api/photos/${photoId}/image?v=${version}`}
                        alt={`Photo ${photoId}`}
                        onLoad={recalc}
                        style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", objectFit: "contain" }}
                    />
                    {hoveredObject &&
                        dims &&
                        (() => {
                            const showAll = "boxes" in hoveredObject;
                            const { reference } = hoveredObject;
                            const boxes = showAll
                                ? dedupeObjectBoxes(hoveredObject.boxes)
                                : [{ box: hoveredObject.box, confidence: 1 }];
                            const regions = showAll ? confidenceRegions(boxes) : [];
                            const mappedBoxes = boxes.flatMap((entry) => {
                                const rect = objectRect({ box: entry.box, reference }, dims);
                                return rect ? [{ ...entry, rect }] : [];
                            });
                            const mappedRegions = regions.flatMap((region) => {
                                const rect = objectRect({ box: region.box, reference }, dims);
                                return rect ? [{ ...region, rect }] : [];
                            });

                            if (mappedBoxes.length === 0) {
                                return null;
                            }

                            return (
                                <svg
                                    style={{
                                        position: "absolute",
                                        top: 0,
                                        left: 0,
                                        width: "100%",
                                        height: "100%",
                                        pointerEvents: "none",
                                    }}
                                >
                                    {mappedRegions.map((region, index) => (
                                        <rect
                                            key={`confidence-${index}`}
                                            x={region.rect.x}
                                            y={region.rect.y}
                                            width={region.rect.width}
                                            height={region.rect.height}
                                            fill="red"
                                            fillOpacity={confidenceOpacity(region.confidence)}
                                        />
                                    ))}
                                    {mappedBoxes.map((entry, index) => (
                                        <rect
                                            key={`box-${index}`}
                                            x={entry.rect.x}
                                            y={entry.rect.y}
                                            width={entry.rect.width}
                                            height={entry.rect.height}
                                            fill={showAll ? "none" : "rgba(255,0,0,0.15)"}
                                            stroke="red"
                                            strokeWidth={2}
                                        />
                                    ))}
                                </svg>
                            );
                        })()}
                    {hoveredTilt &&
                        dims &&
                        (() => {
                            const { line, reference } = hoveredTilt;
                            const toX = (x: number) => dims.ox + x * dims.nw * dims.scale;
                            const toY = (y: number) => dims.oy + y * dims.nh * dims.scale;
                            const x1 = toX(line.x1);
                            const y1 = toY(line.y1);
                            const x2 = toX(line.x2);
                            const y2 = toY(line.y2);
                            const rx = toX(reference.x);
                            const ry = toY(reference.y);
                            const half = Math.hypot(x2 - x1, y2 - y1) / 2;

                            return (
                                <svg
                                    style={{
                                        position: "absolute",
                                        top: 0,
                                        left: 0,
                                        width: "100%",
                                        height: "100%",
                                        pointerEvents: "none",
                                    }}
                                >
                                    <defs>
                                        <clipPath id="tilt-clip">
                                            <rect
                                                x={dims.ox}
                                                y={dims.oy}
                                                width={dims.nw * dims.scale}
                                                height={dims.nh * dims.scale}
                                            />
                                        </clipPath>
                                    </defs>
                                    <g clipPath="url(#tilt-clip)">
                                        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="red" strokeWidth={2} />
                                        <line
                                            x1={rx - half}
                                            y1={ry}
                                            x2={rx + half}
                                            y2={ry}
                                            stroke="#00c853"
                                            strokeWidth={2}
                                            strokeDasharray="6 4"
                                        />
                                        <circle cx={rx} cy={ry} r={5} fill="none" stroke="white" strokeWidth={2} />
                                        <circle cx={rx} cy={ry} r={2.5} fill="#ffb300" />
                                    </g>
                                </svg>
                            );
                        })()}
                </>
            )}
        </Box>
    );
}
