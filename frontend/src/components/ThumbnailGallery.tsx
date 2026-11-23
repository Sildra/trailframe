import { Box } from "@mui/material";
import type { components } from "../api/generated/schema";
import ThumbnailItem from "./ThumbnailItem";

type Fingerprint = components["schemas"]["Fingerprint"];

interface ThumbnailGalleryProps {
    photoIds: number[];
    selectedPhotoId: number | null;
    favorites?: Set<number>;
    thumbSize?: number;
    version?: number;
    /** Turns the thumbnails into a checkbox selection. */
    checkedIds?: Set<number>;
    onToggleCheck?: (photoId: number) => void;
    badges?: Record<number, string>;
    /** Photos with unsaved local edits. */
    editedIds?: Set<number>;
    /** Photo whose parameters are used as the normalization reference. */
    referenceId?: number | null;
    /** Fingerprint boxes, shown only while multi-edit is active. */
    fingerprints?: Record<number, Fingerprint | null | undefined>;
    onSelect: (photoId: number) => void;
}

export default function ThumbnailGallery({
    photoIds,
    selectedPhotoId,
    favorites,
    thumbSize,
    version,
    checkedIds,
    onToggleCheck,
    badges,
    editedIds,
    referenceId,
    fingerprints,
    onSelect,
}: ThumbnailGalleryProps) {
    const checkable = onToggleCheck !== undefined;

    return (
        <Box
            sx={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
                width: "100%",
            }}
        >
            {photoIds.map((photoId) => (
                <ThumbnailItem
                    key={photoId}
                    photoId={photoId}
                    selected={photoId === selectedPhotoId}
                    favorite={favorites?.has(photoId) ?? false}
                    size={thumbSize}
                    version={version}
                    checkable={checkable}
                    checked={checkedIds?.has(photoId) ?? false}
                    onToggleCheck={onToggleCheck ? () => onToggleCheck(photoId) : undefined}
                    badge={badges?.[photoId]}
                    edited={editedIds?.has(photoId) ?? false}
                    reference={referenceId === photoId}
                    fingerprint={fingerprints?.[photoId]}
                    onSelect={() => onSelect(photoId)}
                />
            ))}
        </Box>
    );
}
