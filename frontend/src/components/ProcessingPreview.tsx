import { useId } from "react";
import { Box, CircularProgress, Typography } from "@mui/material";
import type { PreviewModel } from "../lib/preview";

interface ProcessingPreviewProps {
    imageUrl: string | null;
    model: PreviewModel | null;
    loading: boolean;
    error: string | null;
}

/** The live photo preview: the original rotated by the correction, with the crop shadowed. */
export default function ProcessingPreview({ imageUrl, model, loading, error }: ProcessingPreviewProps) {
    const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");

    if (loading) {
        return (
            <Box sx={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", bgcolor: "#161616" }}>
                <CircularProgress size={32} />
            </Box>
        );
    }

    if (error || !imageUrl || !model) {
        return (
            <Box sx={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", bgcolor: "#161616", p: 3 }}>
                <Typography color="text.secondary" align="center">
                    {error ?? "No preview available."}
                </Typography>
            </Box>
        );
    }

    const { image, canvas, padding, crop, trims, horizon, level, marker, angle } = model;
    const viewX = -padding;
    const viewY = -padding;
    const viewWidth = canvas.width + padding * 2;
    const viewHeight = canvas.height + padding * 2;
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    const rotate = `translate(${centerX} ${centerY}) rotate(${-angle})`;
    const clipId = `processing-image-${uid}`;
    const markerRadius = Math.max(canvas.width, canvas.height) * 0.008;

    return (
        <Box sx={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", bgcolor: "#161616" }}>
            <svg
                viewBox={`${viewX} ${viewY} ${viewWidth} ${viewHeight}`}
                preserveAspectRatio="xMidYMid meet"
                style={{ display: "block", width: "100%", height: "100%" }}
            >
                <defs>
                    <clipPath id={clipId} clipPathUnits="userSpaceOnUse">
                        <rect
                            x={image.x}
                            y={image.y}
                            width={image.width}
                            height={image.height}
                            transform={rotate}
                        />
                    </clipPath>
                </defs>

                <g clipPath={`url(#${clipId})`}>
                    <g transform={rotate}>
                        <image
                            href={imageUrl}
                            x={image.x}
                            y={image.y}
                            width={image.width}
                            height={image.height}
                            preserveAspectRatio="none"
                        />
                        {horizon && (
                            <line
                                x1={horizon.x1}
                                y1={horizon.y1}
                                x2={horizon.x2}
                                y2={horizon.y2}
                                stroke="#ff5252"
                                strokeWidth={2}
                                vectorEffect="non-scaling-stroke"
                            />
                        )}
                    </g>

                    {trims && (
                        <>
                            <rect x={viewX} y={viewY} width={viewWidth} height={Math.max(0, crop.y - viewY)} fill="rgba(0,0,0,0.6)" />
                            <rect
                                x={viewX}
                                y={crop.y + crop.height}
                                width={viewWidth}
                                height={Math.max(0, viewY + viewHeight - crop.y - crop.height)}
                                fill="rgba(0,0,0,0.6)"
                            />
                            <rect x={viewX} y={crop.y} width={Math.max(0, crop.x - viewX)} height={crop.height} fill="rgba(0,0,0,0.6)" />
                            <rect
                                x={crop.x + crop.width}
                                y={crop.y}
                                width={Math.max(0, viewX + viewWidth - crop.x - crop.width)}
                                height={crop.height}
                                fill="rgba(0,0,0,0.6)"
                            />
                        </>
                    )}
                </g>

                {trims && (
                    <rect
                        x={crop.x}
                        y={crop.y}
                        width={crop.width}
                        height={crop.height}
                        fill="none"
                        stroke="rgba(255,255,255,0.9)"
                        strokeWidth={1.5}
                        vectorEffect="non-scaling-stroke"
                    />
                )}

                <line
                    x1={level.x1}
                    y1={level.y1}
                    x2={level.x2}
                    y2={level.y2}
                    stroke="#00e676"
                    strokeWidth={2}
                    strokeDasharray="6 4"
                    vectorEffect="non-scaling-stroke"
                />

                <circle
                    cx={marker.x}
                    cy={marker.y}
                    r={markerRadius}
                    fill="none"
                    stroke="white"
                    strokeWidth={2}
                    vectorEffect="non-scaling-stroke"
                />
                <circle cx={marker.x} cy={marker.y} r={markerRadius * 0.45} fill="#ffb300" />
            </svg>
        </Box>
    );
}
