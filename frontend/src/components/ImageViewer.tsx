import { useCallback, useEffect, useRef, useState } from "react";
import { Box, Typography } from "@mui/material";

interface ImageViewerProps {
    photoId: number | null;
    hoveredBox?: number[] | null;
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

export default function ImageViewer({ photoId, hoveredBox }: ImageViewerProps) {
    const imgRef = useRef<HTMLImageElement>(null);
    const [dims, setDims] = useState<ReturnType<typeof computeDims> | null>(null);

    const recalc = useCallback(() => {
        if (imgRef.current) {
            setDims(computeDims(imgRef.current));
        }
    }, []);

    useEffect(() => {
        window.addEventListener("resize", recalc);

        return () => window.removeEventListener("resize", recalc);
    }, [recalc]);

    return (
        <Box sx={{ width: "100%", height: "100%", position: "relative" }}>
            {photoId === null ? (
                <Box sx={{ display: "flex", alignItems: "center", justifyContent: "center", width: "100%", height: "100%" }}>
                    <Typography color="text.secondary">Select a photo</Typography>
                </Box>
            ) : (
                <>
                    <img
                        key={photoId}
                        ref={imgRef}
                        src={`/api/photos/${photoId}/image`}
                        alt={`Photo ${photoId}`}
                        onLoad={recalc}
                        style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", objectFit: "contain" }}
                    />
                    {hoveredBox &&
                        dims &&
                        (() => {
                            const { scale, ox, oy } = dims;
                            const [x1, y1, x2, y2] = hoveredBox;

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
                                    <rect
                                        x={ox + x1 * scale}
                                        y={oy + y1 * scale}
                                        width={(x2 - x1) * scale}
                                        height={(y2 - y1) * scale}
                                        fill="rgba(255,0,0,0.15)"
                                        stroke="red"
                                        strokeWidth={2}
                                    />
                                </svg>
                            );
                        })()}
                </>
            )}
        </Box>
    );
}
