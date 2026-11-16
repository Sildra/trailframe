import { Box } from "@mui/material";
import ThumbnailItem from "./ThumbnailItem";

interface ThumbnailGalleryProps {
    photoIds: number[];
    selectedPhotoId: number | null;
    favorites?: Set<number>;
    thumbSize?: number;
    version?: number;
    onSelect: (photoId: number) => void;
}

export default function ThumbnailGallery({ photoIds, selectedPhotoId, favorites, thumbSize, version, onSelect }: ThumbnailGalleryProps) {
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
                    onSelect={() => onSelect(photoId)}
                />
            ))}
        </Box>
    );
}
