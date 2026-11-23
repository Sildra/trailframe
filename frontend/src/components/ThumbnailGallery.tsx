import { Box } from "@mui/material";
import ThumbnailItem from "./ThumbnailItem";

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
                    onSelect={() => (checkable && onToggleCheck ? onToggleCheck(photoId) : onSelect(photoId))}
                />
            ))}
        </Box>
    );
}
