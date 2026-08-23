import { useState } from "react";
import { Box } from "@mui/material";
import type { components } from "../api/generated/schema";
import { project } from "../lib/projection";

type PhotoMap = components["schemas"]["PhotoMap"];

interface WireframeMapProps {
    photoId: number;
    wireframe: string | null;
    map: PhotoMap | null;
    className?: string;
}

interface Display {
    photoId: number;
    wireframe: string;
    map: PhotoMap;
}

export default function WireframeMap({ photoId, wireframe, map, className }: WireframeMapProps) {
    const [display, setDisplay] = useState<Display | null>(() =>
        wireframe && map ? { photoId, wireframe, map } : null,
    );
    const [failed, setFailed] = useState<Display | null>(null);

    if (wireframe && map) {
        if (!display || display.wireframe !== wireframe) {
            setDisplay({ photoId, wireframe, map });
        } else if (display.map.point !== map.point) {
            setDisplay({ ...display, map: { ...display.map, point: map.point } });
        }
    }

    if (!display || failed === display) {
        return null;
    }

    const point = display.map.point;
    const dot = point ? project(point.lat, point.lon, display.map) : null;

    return (
        <Box className={className} sx={{ position: "relative", bgcolor: "#ffffff" }}>
            <img
                src={`/api/photos/${display.photoId}/wireframe`}
                alt="Location map"
                onError={() => setFailed(display)}
                style={{
                    display: "block",
                    width: "100%",
                    height: "auto",
                    filter: "grayscale(100%) sepia(100%) hue-rotate(180deg) saturate(300%)",
                }}
            />
            {dot && (
                <svg
                    viewBox={`0 0 ${display.map.width} ${display.map.height}`}
                    style={{ position: "absolute", inset: 0, width: "100%", height: "100%", display: "block" }}
                >
                    <circle cx={dot[0]} cy={dot[1]} r={7} fill="#e11d48" stroke="#ffffff" strokeWidth={2} />
                </svg>
            )}
        </Box>
    );
}
