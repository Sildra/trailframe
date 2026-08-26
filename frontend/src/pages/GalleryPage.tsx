import { useCallback, useEffect, useMemo, useState } from "react";
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton } from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DeleteIcon from "@mui/icons-material/Delete";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import GroupedGallery from "../components/GroupedGallery";
import ImageViewer from "../components/ImageViewer";
import PhotoMetadata from "../components/PhotoMetadata";
import UploadButton from "../components/UploadButton";
import { groupKey } from "../lib/groups";

type PhotoGroupSummary = components["schemas"]["PhotoGroupSummary"];

export default function GalleryPage() {
    const [selectedPhotoId, setSelectedPhotoId] = useState<number | null>(null);
    const [groups, setGroups] = useState<PhotoGroupSummary[] | null>(null);
    const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
    const [leftCollapsed, setLeftCollapsed] = useState(false);
    const [rightCollapsed, setRightCollapsed] = useState(false);
    const [hoveredBox, setHoveredBox] = useState<number[] | null>(null);
    const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
    const [favoriteIds, setFavoriteIds] = useState<Set<number>>(new Set());

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/photos/favorites")
            .then(({ data }) => {
                if (!cancelled && data) {
                    setFavoriteIds(new Set(data));
                }
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, []);

    const toggleFavorite = useCallback(
        (photoId: number) => {
            const value = !favoriteIds.has(photoId);

            setFavoriteIds((previous) => {
                const next = new Set(previous);

                if (value) {
                    next.add(photoId);
                } else {
                    next.delete(photoId);
                }

                return next;
            });

            api.PUT("/api/photos/{photo_id}/favorite", {
                params: { path: { photo_id: photoId } },
                body: { value },
            }).catch(() => {});
        },
        [favoriteIds],
    );

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/photos/groups")
            .then(({ data, error }) => {
                if (cancelled) {
                    return;
                }
                if (error || data === undefined) {
                    setGroups([]);
                    return;
                }
                setGroups(data);
                setCollapsed(new Set(data.slice(1).map(groupKey)));
            })
            .catch(() => {
                if (!cancelled) {
                    setGroups([]);
                }
            });

        return () => {
            cancelled = true;
        };
    }, []);

    const refresh = async () => {
        const { data, error } = await api.GET("/api/photos/groups");

        if (error || data === undefined) {
            return;
        }

        setGroups(data);
        setCollapsed(new Set(data.slice(1).map(groupKey)));
    };

    const toggle = (key: string) => {
        setCollapsed((previous) => {
            const next = new Set(previous);

            if (next.has(key)) {
                next.delete(key);
            } else {
                next.add(key);
            }

            return next;
        });
    };

    const orderedPhotoIds = useMemo(() => {
        if (!groups) {
            return [];
        }

        return groups.flatMap((group) => (collapsed.has(groupKey(group)) ? [] : group.photo_ids ?? []));
    }, [groups, collapsed]);

    const deletePhoto = useCallback(() => {
        if (selectedPhotoId === null) {
            return;
        }

        const photoId = selectedPhotoId;
        const index = orderedPhotoIds.indexOf(photoId);

        let nextId: number | null = null;

        if (index !== -1) {
            if (index + 1 < orderedPhotoIds.length) {
                nextId = orderedPhotoIds[index + 1];
            } else if (index - 1 >= 0) {
                nextId = orderedPhotoIds[index - 1];
            }
        }

        setSelectedPhotoId(nextId);
        setConfirmDeleteOpen(false);
        setHoveredBox(null);

        setGroups((previous) =>
            previous?.map((group) => ({
                ...group,
                photo_ids: (group.photo_ids ?? []).filter((id) => id !== photoId),
            })) ?? null,
        );

        api.DELETE("/api/photos/{photo_id}", { params: { path: { photo_id: photoId } } });
    }, [selectedPhotoId, orderedPhotoIds]);

    useEffect(() => {
        function onKeyDown(event: KeyboardEvent) {
            const keyHandled = event.key === "ArrowLeft" || event.key === "ArrowRight" || event.key === "f";

            if (!keyHandled) {
                return;
            }

            const target = event.target as HTMLElement | null;

            if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) {
                return;
            }

            if (event.key === "f") {
                if (selectedPhotoId !== null) {
                    event.preventDefault();
                    toggleFavorite(selectedPhotoId);
                }

                return;
            }

            if (orderedPhotoIds.length === 0) {
                return;
            }

            event.preventDefault();

            setSelectedPhotoId((current) => {
                const lastIndex = orderedPhotoIds.length - 1;

                if (current == null) {
                    return event.key === "ArrowRight" ? orderedPhotoIds[0] : orderedPhotoIds[lastIndex];
                }

                const index = orderedPhotoIds.indexOf(current);

                if (index === -1) {
                    return event.key === "ArrowRight" ? orderedPhotoIds[0] : orderedPhotoIds[lastIndex];
                }

                if (event.key === "ArrowRight") {
                    return orderedPhotoIds[(index + 1) % orderedPhotoIds.length];
                }

                return orderedPhotoIds[(index - 1 + orderedPhotoIds.length) % orderedPhotoIds.length];
            });
            setHoveredBox(null);
        }

        window.addEventListener("keydown", onKeyDown);

        return () => window.removeEventListener("keydown", onKeyDown);
    }, [orderedPhotoIds, selectedPhotoId, toggleFavorite]);

    useEffect(() => {
        if (selectedPhotoId === null || orderedPhotoIds.length === 0) {
            return;
        }

        const index = orderedPhotoIds.indexOf(selectedPhotoId);

        const ids = index === -1
            ? [selectedPhotoId]
            : [orderedPhotoIds[index - 1], selectedPhotoId, orderedPhotoIds[index + 1]].filter(
                  (id): id is number => id != null,
              );

        for (const id of ids) {
            const img = new Image();
            img.src = `./api/photos/${id}/image`;
        }
    }, [selectedPhotoId, orderedPhotoIds]);

    return (
        <Box sx={{ flex: 1, minHeight: 0, display: "flex" }}>
            <Box
                sx={{
                    display: "flex",
                    flexDirection: "column",
                    width: leftCollapsed ? 60 : 320,
                    flexShrink: 0,
                    borderRight: 1,
                    borderColor: "divider",
                    transition: "width 0.2s",
                }}
            >
                <Box sx={{ display: "flex", justifyContent: "center", py: 0.5 }}>
                    <IconButton
                        size="small"
                        onClick={() => setLeftCollapsed(!leftCollapsed)}
                        aria-label={leftCollapsed ? "Show thumbnails" : "Hide thumbnails"}
                    >
                        {leftCollapsed ? <ChevronRightIcon /> : <ChevronLeftIcon />}
                    </IconButton>
                </Box>
                {!leftCollapsed && (
                    <Box
                        sx={{
                            flex: 1,
                            minHeight: 0,
                            overflowY: "auto",
                            display: "flex",
                            flexDirection: "column",
                        }}
                    >
                        <GroupedGallery
                            groups={groups}
                            collapsed={collapsed}
                            selectedPhotoId={selectedPhotoId}
                            favorites={favoriteIds}
                            onSelect={setSelectedPhotoId}
                            onToggle={toggle}
                            onRefresh={refresh}
                        />
                    </Box>
                )}
            </Box>
            <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <ImageViewer photoId={selectedPhotoId} hoveredBox={hoveredBox} />
            </Box>
            <Box
                sx={{
                    display: "flex",
                    flexDirection: "column",
                    width: rightCollapsed ? 60 : 320,
                    flexShrink: 0,
                    borderLeft: 1,
                    borderColor: "divider",
                    transition: "width 0.2s",
                }}
            >
                <Box sx={{ display: "flex", justifyContent: "center", py: 0.5 }}>
                    <IconButton
                        size="small"
                        onClick={() => setRightCollapsed(!rightCollapsed)}
                        aria-label={rightCollapsed ? "Show upload" : "Hide upload"}
                    >
                        {rightCollapsed ? <ChevronLeftIcon /> : <ChevronRightIcon />}
                    </IconButton>
                </Box>
                {!rightCollapsed && (
                    <Box
                        sx={{
                            flex: 1,
                            minHeight: 0,
                            overflowY: "auto",
                            display: "flex",
                            flexDirection: "column",
                            gap: 1,
                        }}
                    >
                        <UploadButton />
                        {selectedPhotoId !== null && (
                            <Box sx={{ display: "flex", justifyContent: "center" }}>
                                <IconButton color="error" size="small" onClick={() => setConfirmDeleteOpen(true)}>
                                    <DeleteIcon fontSize="small" />
                                </IconButton>
                            </Box>
                        )}
                        {selectedPhotoId !== null && (
                            <PhotoMetadata
                                photoId={selectedPhotoId}
                                favorite={favoriteIds.has(selectedPhotoId)}
                                onToggleFavorite={() => toggleFavorite(selectedPhotoId)}
                                onHoverObject={setHoveredBox}
                                onSelectPhoto={setSelectedPhotoId}
                            />
                        )}
                    </Box>
                )}
            </Box>
            <Dialog open={confirmDeleteOpen} onClose={() => setConfirmDeleteOpen(false)}>
                <DialogTitle>Delete Photo</DialogTitle>
                <DialogContent>
                    Are you sure you want to delete this photo?
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setConfirmDeleteOpen(false)}>Cancel</Button>
                    <Button color="error" onClick={deletePhoto}>Delete</Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
}
