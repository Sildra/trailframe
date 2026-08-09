import { Fragment, useEffect, useState } from "react";
import { Accordion, AccordionDetails, AccordionSummary, Box, IconButton, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import StarIcon from "@mui/icons-material/Star";
import StarBorderIcon from "@mui/icons-material/StarBorder";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import { formatDateTime } from "../lib/format";
import ThumbnailGallery from "./ThumbnailGallery";
import WireframeMap from "./WireframeMap";

type Photo = components["schemas"]["PhotoDetail"];

interface DetectedObject {
    label: string;
    confidence: number;
    box?: number[];
}

interface PhotoMetadataProps {
    photoId: number;
    favorite?: boolean;
    onToggleFavorite?: () => void;
    onHoverObject?: (box: number[] | null) => void;
    onSelectPhoto?: (photoId: number) => void;
}

function formatDate(date: string | null | undefined): string {
    if (!date) {
        return "";
    }

    return formatDateTime(date);
}

function formatValue(value: unknown): string {
    if (value === null || value === undefined || value === "") {
        return "";
    }

    return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function MetadataList({ entries, mono }: { entries: Array<[string, string]>; mono?: boolean }) {
    return (
        <Box
            sx={{
                display: "grid",
                gridTemplateColumns: "auto 1fr",
                gap: "4px 12px",
                fontSize: 13,
            }}
        >
            {entries.map(([key, value]) => (
                <Fragment key={key}>
                    <Box component="dt" sx={{ color: "text.secondary" }}>
                        {key}
                    </Box>
                    <Box component="dd" sx={{ margin: 0, wordBreak: "break-word", fontFamily: mono ? "monospace" : undefined }}>
                        {value}
                    </Box>
                </Fragment>
            ))}
        </Box>
    );
}

export default function PhotoMetadata({ photoId, favorite = false, onToggleFavorite, onHoverObject, onSelectPhoto }: PhotoMetadataProps) {
    const [photo, setPhoto] = useState<Photo | null>(null);

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/photos/{photo_id}/data", {
            params: { path: { photo_id: photoId } },
        })
            .then(({ data, error }) => {
                if (cancelled || error || !data) {
                    return;
                }
                setPhoto(data);
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, [photoId]);

    if (!photo) {
        return <Typography sx={{ fontSize: 13, color: "text.secondary" }}>Loading…</Typography>;
    }

    const dataEntries: Array<[string, string]> = [];
    const filename = photo.path.split(/[\\/]/).pop();
    if (filename) {
        dataEntries.push(["Filename", filename]);
    }
    const date = formatDate(photo.date);
    if (date) {
        dataEntries.push(["Date", date]);
    }
    if (photo.latitude != null && photo.longitude != null) {
        dataEntries.push([
            "Coordinates",
            `${photo.latitude.toFixed(6)}, ${photo.longitude.toFixed(6)}`,
        ]);
    }
    if (photo.location) {
        dataEntries.push(["Location", photo.location]);
    }
    if (photo.country) {
        dataEntries.push(["Country", photo.country]);
    }
    const scanners = (photo.scanners ?? []).filter((scanner) => scanner !== "");
    if (scanners.length > 0) {
        dataEntries.push(["Scanners", scanners.join(", ")]);
    }
    if (photo.scores) {
        for (const [key, value] of Object.entries(photo.scores)) {
            dataEntries.push([`${key} score`, formatValue(value)]);
        }
    }

    const objects = ((photo.objects ?? []) as unknown as DetectedObject[]).filter((obj) => obj && typeof obj.label === "string");

    const exifEntries = Object.entries(photo.exif ?? {}).filter(
        ([, value]) => formatValue(value) !== "",
    );
    const tags = (photo.tags ?? []).filter((tag) => tag !== "");
    const groups = (photo.groups ?? []).filter((g) => g.photo_ids.length > 0);
    const mapShown = Boolean(photo.wireframe && photo.map);

    return (
        <Box sx={{ width: "100%", textAlign: "left" }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, mb: 1 }}>
                <IconButton
                    size="small"
                    aria-label={favorite ? "Remove from favorites" : "Add to favorites"}
                    aria-pressed={favorite}
                    onClick={() => onToggleFavorite?.()}
                >
                    {favorite ? <StarIcon sx={{ color: "#ffb300" }} /> : <StarBorderIcon />}
                </IconButton>
                <Typography sx={{ fontSize: 13, color: favorite ? "text.primary" : "text.secondary" }}>
                    {favorite ? "In favorites" : "Favorite"}
                </Typography>
            </Box>
            {dataEntries.length > 0 && (
                <Accordion defaultExpanded disableGutters>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ fontWeight: 600, fontSize: 14 }}>
                        Data
                    </AccordionSummary>
                    <AccordionDetails>
                        <MetadataList entries={dataEntries} />
                    </AccordionDetails>
                </Accordion>
            )}
            {exifEntries.length > 0 && (
                <Accordion disableGutters>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ fontWeight: 600, fontSize: 14 }}>
                        EXIF
                    </AccordionSummary>
                    <AccordionDetails>
                        <MetadataList
                            entries={exifEntries.map(
                                ([key, value]) => [key, formatValue(value)] as [string, string],
                            )}
                            mono
                        />
                    </AccordionDetails>
                </Accordion>
            )}
            {tags.length > 0 && (
                <Accordion disableGutters>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ fontWeight: 600, fontSize: 14 }}>
                        Tags
                    </AccordionSummary>
                    <AccordionDetails>
                        <Typography sx={{ fontSize: 13 }}>{tags.join(", ")}</Typography>
                    </AccordionDetails>
                </Accordion>
            )}
            {objects.length > 0 && (
                <Accordion disableGutters>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ fontWeight: 600, fontSize: 14 }}>
                        Objects
                    </AccordionSummary>
                    <AccordionDetails>
                        <Box
                            sx={{ display: "flex", flexDirection: "column", gap: "2px" }}
                            onMouseLeave={() => onHoverObject?.(null)}
                        >
                            {objects.map((obj, i) => (
                                <Box
                                    key={i}
                                    sx={{
                                        display: "flex",
                                        justifyContent: "space-between",
                                        fontSize: 13,
                                        px: 0.5,
                                        borderRadius: 1,
                                        cursor: "default",
                                        "&:hover": { bgcolor: "action.hover" },
                                    }}
                                    onMouseEnter={() => obj.box && onHoverObject?.(obj.box)}
                                >
                                    <span>{obj.label}</span>
                                    <span style={{ opacity: 0.6 }}>{Math.round((obj.confidence ?? 0) * 100)}%</span>
                                </Box>
                            ))}
                        </Box>
                    </AccordionDetails>
                </Accordion>
            )}
            {groups.map((group) => (
                <Accordion key={group.name} disableGutters>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ fontWeight: 600, fontSize: 14 }}>
                        {group.name} ({group.photo_ids.length})
                    </AccordionSummary>
                    <AccordionDetails sx={{ p: 0 }}>
                        <ThumbnailGallery
                            photoIds={group.photo_ids}
                            selectedPhotoId={photoId}
                            onSelect={onSelectPhoto ?? (() => {})}
                        />
                    </AccordionDetails>
                </Accordion>
            ))}
            {mapShown && (
                <Accordion defaultExpanded disableGutters>
                    <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ fontWeight: 600, fontSize: 14 }}>
                        Location map
                    </AccordionSummary>
                    <AccordionDetails>
                        <WireframeMap
                            photoId={photoId}
                            wireframe={photo?.wireframe ?? null}
                            map={photo?.map ?? null}
                        />
                    </AccordionDetails>
                </Accordion>
            )}
        </Box>
    );
}
