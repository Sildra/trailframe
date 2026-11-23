import { useEffect, useRef, useState } from "react";
import { Box, Checkbox, Chip } from "@mui/material";
import StarIcon from "@mui/icons-material/Star";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";

type Fingerprint = components["schemas"]["Fingerprint"];

interface ThumbnailItemProps {
    photoId: number;
    selected?: boolean;
    favorite?: boolean;
    /** Preferred thumbnail height (px); the backend picks the closest generated size. */
    size?: number;
    /** Bumped when the photo's files change, so the thumbnail is fetched again. */
    version?: number;
    /** Show a selection checkbox on the thumbnail. */
    checkable?: boolean;
    checked?: boolean;
    onToggleCheck?: () => void;
    /** Short overlay label, e.g. the similarity score. */
    badge?: string;
    /** Marks locally edited parameters that have not been saved yet. */
    edited?: boolean;
    /** Outlines the normalization reference in a distinct colour. */
    reference?: boolean;
    /** Fingerprint boxes drawn over the thumbnail in multi-edit mode. */
    fingerprint?: Fingerprint | null;
    onSelect: () => void;
}

export default function ThumbnailItem({
    photoId,
    selected = false,
    favorite = false,
    size = 160,
    version = 0,
    checkable = false,
    checked = false,
    onToggleCheck,
    badge,
    edited = false,
    reference = false,
    fingerprint,
    onSelect,
}: ThumbnailItemProps) {
    const rootRef = useRef<HTMLDivElement | null>(null);
    const [visible, setVisible] = useState(false);
    const [src, setSrc] = useState<string | null>(null);

    useEffect(() => {
        const element = rootRef.current;
        if (!element) {
            return;
        }

        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    setVisible(true);
                    observer.disconnect();
                }
            },
            { rootMargin: "200px" },
        );

        observer.observe(element);

        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        if (!visible) {
            return;
        }

        let cancelled = false;
        let objectUrl: string | null = null;

        api.GET("/api/photos/{photo_id}/thumbnail", {
            params: { path: { photo_id: photoId }, query: { size, v: String(version) } },
            parseAs: "blob",
        })
            .then(({ data, error }) => {
                if (cancelled || error || !data) {
                    return;
                }

                objectUrl = URL.createObjectURL(data as Blob);
                setSrc(objectUrl);
            })
            .catch(() => {});

        return () => {
            cancelled = true;
            if (objectUrl) {
                URL.revokeObjectURL(objectUrl);
            }
        };
    }, [visible, photoId, size, version]);

    return (
        <Box
            ref={rootRef}
            role="button"
            tabIndex={0}
            onClick={onSelect}
            onKeyDown={(event) => {
                if (event.key === "Enter") {
                    onSelect();
                }
            }}
            sx={(theme) => ({
                position: "relative",
                aspectRatio: "16 / 10",
                overflow: "hidden",
                bgcolor: "action.hover",
                cursor: "pointer",
                outline: reference
                    ? `2px solid ${theme.palette.secondary.main}`
                    : selected
                      ? `2px solid ${theme.palette.primary.main}`
                      : "none",
                outlineOffset: -2,
            })}
        >
            {src ? (
                fingerprint ? (
                    <svg
                        viewBox={`0 0 ${fingerprint.reference.width} ${fingerprint.reference.height}`}
                        preserveAspectRatio="xMidYMid slice"
                        role="img"
                        aria-label={`Photo ${photoId}`}
                        style={{ display: "block", width: "100%", height: "100%" }}
                    >
                        <image
                            href={src}
                            x={0}
                            y={0}
                            width={fingerprint.reference.width}
                            height={fingerprint.reference.height}
                            preserveAspectRatio="none"
                        />
                        {fingerprint.markers.map((marker, index) => (
                            <rect
                                key={`${marker.key}-${index}`}
                                x={marker.box[0] * fingerprint.reference.width}
                                y={marker.box[1] * fingerprint.reference.height}
                                width={Math.max(0, (marker.box[2] - marker.box[0]) * fingerprint.reference.width)}
                                height={Math.max(0, (marker.box[3] - marker.box[1]) * fingerprint.reference.height)}
                                fill="none"
                                stroke={marker.shared ? "#00e676" : "rgba(255, 255, 255, 0.9)"}
                                strokeWidth={marker.shared ? 2 : 1}
                                vectorEffect="non-scaling-stroke"
                            >
                                <title>{`${marker.label}${marker.shared ? " (shared)" : ""}`}</title>
                            </rect>
                        ))}
                    </svg>
                ) : (
                    <img
                        src={src}
                        alt={`Photo ${photoId}`}
                        style={{ display: "block", width: "100%", height: "100%", objectFit: "cover" }}
                    />
                )
            ) : (
                <Box
                    sx={{
                        width: "100%",
                        height: "100%",
                        bgcolor: "rgba(224, 224, 224, 0.63)",
                        boxShadow: "inset 0 2px 8px rgba(0, 0, 0, 0.15)",
                    }}
                />
            )}
            {checkable && (
                <Checkbox
                    size="small"
                    checked={checked}
                    onChange={() => onToggleCheck?.()}
                    onClick={(event) => event.stopPropagation()}
                    slotProps={{ input: { "aria-label": `Select photo ${photoId}` } }}
                    sx={{ position: "absolute", top: 0, left: 0, p: 0.5, bgcolor: "background.paper" }}
                />
            )}
            {favorite && (
                <StarIcon
                    fontSize="small"
                    sx={{
                        position: "absolute",
                        top: edited ? 22 : 2,
                        right: 2,
                        color: "#ffb300",
                        filter: "drop-shadow(0 1px 1px rgba(0, 0, 0, 0.6))",
                        pointerEvents: "none",
                    }}
                />
            )}
            {edited && (
                <Chip
                    size="small"
                    label="edited"
                    color="warning"
                    sx={{
                        position: "absolute",
                        top: 2,
                        right: 2,
                        height: 18,
                        "& .MuiChip-label": { px: 0.75, fontSize: 10 },
                        pointerEvents: "none",
                    }}
                />
            )}
            {badge && (
                <Chip
                    size="small"
                    label={badge}
                    color={checked ? "primary" : "default"}
                    sx={{
                        position: "absolute",
                        bottom: 2,
                        right: 2,
                        height: 20,
                        "& .MuiChip-label": { px: 0.75, fontSize: 11 },
                        pointerEvents: "none",
                    }}
                />
            )}
        </Box>
    );
}
