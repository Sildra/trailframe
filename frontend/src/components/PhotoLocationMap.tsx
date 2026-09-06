import { useEffect, useRef } from "react";
import { Box } from "@mui/material";
import { Circle, CircleMarker, MapContainer, TileLayer, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import type { components } from "../api/generated/schema";

type LocationEstimate = components["schemas"]["LocationEstimate"];

interface PhotoLocationMapProps {
    latitude: number;
    longitude: number;
    estimate?: LocationEstimate;
    className?: string;
}

function ReCenter({ latitude, longitude }: { latitude: number; longitude: number }) {
    const map = useMap();
    const ref = useRef({ latitude, longitude });

    useEffect(() => {
        if (ref.current.latitude !== latitude || ref.current.longitude !== longitude) {
            ref.current = { latitude, longitude };
            map.setView([latitude, longitude], map.getZoom());
        }
    }, [latitude, longitude, map]);

    return null;
}

export default function PhotoLocationMap({ latitude, longitude, estimate, className }: PhotoLocationMapProps) {
    const showDot = !estimate;

    return (
        <Box className={className} sx={{ borderRadius: 1, overflow: "hidden" }}>
            <MapContainer
                center={[latitude, longitude]}
                zoom={estimate ? 7 : 12}
                style={{ height: 200, width: "100%" }}
                zoomControl={false}
                attributionControl={false}
            >
                <TileLayer url="./api/tiles/{z}/{x}/{y}.png" />
                {showDot && (
                    <CircleMarker
                        center={[latitude, longitude]}
                        radius={7}
                        pathOptions={{ color: "#e53935", fillColor: "#e53935", fillOpacity: 0.8 }}
                    />
                )}
                {estimate && (
                    <Circle
                        center={[latitude, longitude]}
                        radius={estimate.radius_m}
                        pathOptions={{ color: "#e53935", fillColor: "#e53935", fillOpacity: 0.15 }}
                    />
                )}
                <ReCenter latitude={latitude} longitude={longitude} />
            </MapContainer>
        </Box>
    );
}