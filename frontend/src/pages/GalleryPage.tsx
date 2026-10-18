import { useCallback, useEffect, useMemo, useState } from "react";
import {
    Box,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    IconButton,
    Menu,
    MenuItem,
} from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DeleteIcon from "@mui/icons-material/Delete";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import GroupedGallery from "../components/GroupedGallery";
import ImageViewer from "../components/ImageViewer";
import PhotoMetadata from "../components/PhotoMetadata";
import UploadButton from "../components/UploadButton";
import { duplicateKey, groupKey, locationIssueKey } from "../lib/groups";

type PhotoGroupSummary = components["schemas"]["PhotoGroupSummary"];

const MENUS = ["Groups", "Duplicates", "Location Issues"] as const;

type Menu = (typeof MENUS)[number];

export default function GalleryPage() {
    const [selectedPhotoId, setSelectedPhotoId] = useState<number | null>(null);
    const [groups, setGroups] = useState<PhotoGroupSummary[] | null>(null);
    const [duplicates, setDuplicates] = useState<PhotoGroupSummary[] | null>(null);
    const [locationIssues, setLocationIssues] = useState<PhotoGroupSummary[] | null>(null);
    const [menu, setMenu] = useState<Menu>("Groups");
    const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);
    const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
    const [duplicatesCollapsed, setDuplicatesCollapsed] = useState<Set<string>>(new Set());
    const [locationIssuesCollapsed, setLocationIssuesCollapsed] = useState<Set<string>>(new Set());
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

        api.GET("/api/photos/duplicates")
            .then(({ data, error }) => {
                if (cancelled) {
                    return;
                }
                if (error || data === undefined) {
                    setDuplicates([]);
                    return;
                }
                setDuplicates(data);
            })
            .catch(() => {
                if (!cancelled) {
                    setDuplicates([]);
                }
            });

        api.GET("/api/photos/location-issues")
            .then(({ data, error }) => {
                if (cancelled) {
                    return;
                }
                if (error || data === undefined) {
                    setLocationIssues([]);
                    return;
                }
                setLocationIssues(data);
                setLocationIssuesCollapsed(new Set());
            })
            .catch(() => {
                if (!cancelled) {
                    setLocationIssues([]);
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

        const { data: duplicateData, error: duplicateError } = await api.GET("/api/photos/duplicates");

        if (!duplicateError && duplicateData) {
            setDuplicates(duplicateData);
        }

        const { data: locationData, error: locationError } = await api.GET("/api/photos/location-issues");

        if (!locationError && locationData) {
            setLocationIssues(locationData);
        }
    };

    const toggle = useCallback(
        (setter: React.Dispatch<React.SetStateAction<Set<string>>>) => (key: string) => {
            setter((previous) => {
                const next = new Set(previous);

                if (next.has(key)) {
                    next.delete(key);
                } else {
                    next.add(key);
                }

                return next;
            });
        },
        [],
    );

    const toggleCollapsed = useMemo(() => toggle(setCollapsed), [toggle]);
    const toggleDuplicates = useMemo(() => toggle(setDuplicatesCollapsed), [toggle]);
    const toggleLocationIssues = useMemo(() => toggle(setLocationIssuesCollapsed), [toggle]);

    const cycleMenu = (direction: number) => {
        setMenu((current) => MENUS[(MENUS.indexOf(current) + direction + MENUS.length) % MENUS.length]);
    };

    const orderedPhotoIds = useMemo(() => {
        if (menu === "Duplicates") {
            return (duplicates ?? [])
                .filter((group) => !duplicatesCollapsed.has(duplicateKey(group)))
                .flatMap((group) => group.photo_ids ?? []);
        }

        if (menu === "Location Issues") {
            return (locationIssues ?? [])
                .filter((group) => !locationIssuesCollapsed.has(locationIssueKey(group)))
                .flatMap((group) => group.photo_ids ?? []);
        }

        return (groups ?? [])
            .filter((group) => !collapsed.has(groupKey(group)))
            .flatMap((group) => group.photo_ids ?? []);
    }, [groups, collapsed, duplicates, duplicatesCollapsed, locationIssues, locationIssuesCollapsed, menu]);

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

        setDuplicates((previous) => {
            if (!previous) {
                return previous;
            }

            return previous
                .map((group) => ({
                    ...group,
                    photo_ids: (group.photo_ids ?? []).filter((id) => id !== photoId),
                }))
                .filter((group) => (group.photo_ids?.length ?? 0) >= 2);
        });

        setLocationIssues((previous) =>
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

    const gallery = useMemo(() => {
        switch (menu) {
            case "Duplicates":
                return (
                    <GroupedGallery
                        groups={duplicates}
                        collapsed={duplicatesCollapsed}
                        keyFn={duplicateKey}
                        selectedPhotoId={selectedPhotoId}
                        favorites={favoriteIds}
                        showAddGroup={false}
                        deletable={false}
                        emptyMessage="No duplicates found."
                        onSelect={setSelectedPhotoId}
                        onToggle={toggleDuplicates}
                        onRefresh={refresh}
                    />
                );
            case "Location Issues":
                return (
                    <GroupedGallery
                        groups={locationIssues}
                        collapsed={locationIssuesCollapsed}
                        keyFn={locationIssueKey}
                        selectedPhotoId={selectedPhotoId}
                        favorites={favoriteIds}
                        showAddGroup={false}
                        deletable={false}
                        emptyMessage="No location issues found."
                        onSelect={setSelectedPhotoId}
                        onToggle={toggleLocationIssues}
                        onRefresh={refresh}
                    />
                );
            default:
                return (
                    <GroupedGallery
                        groups={groups}
                        collapsed={collapsed}
                        keyFn={groupKey}
                        selectedPhotoId={selectedPhotoId}
                        favorites={favoriteIds}
                        showAddGroup
                        deletable
                        emptyMessage="No groups yet."
                        onSelect={setSelectedPhotoId}
                        onToggle={toggleCollapsed}
                        onRefresh={refresh}
                    />
                );
        }
    }, [menu, groups, duplicates, duplicatesCollapsed, locationIssues, collapsed, locationIssuesCollapsed, selectedPhotoId, favoriteIds, toggleCollapsed, toggleDuplicates, toggleLocationIssues]);

    return (
        <Box sx={{ flex: 1, minHeight: 0, display: "flex" }}>
            <Box
                sx={{
                    display: "flex",
                    flexDirection: "column",
                    width: leftCollapsed ? 40 : 320,
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
                        <Box
                            sx={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                px: 0.5,
                                py: 0.5,
                                borderBottom: 1,
                                borderColor: "divider",
                            }}
                        >
                            <IconButton size="small" onClick={() => cycleMenu(-1)} aria-label="Previous menu">
                                <ChevronLeftIcon fontSize="small" />
                            </IconButton>
                            <Button
                                size="small"
                                sx={{ textTransform: "none", fontWeight: 600, color: "text.primary" }}
                                onClick={(event) => setMenuAnchor(event.currentTarget)}
                            >
                                {menu}
                            </Button>
                            <IconButton size="small" onClick={() => cycleMenu(1)} aria-label="Next menu">
                                <ChevronRightIcon fontSize="small" />
                            </IconButton>
                            <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={() => setMenuAnchor(null)}>
                                {MENUS.map((option) => (
                                    <MenuItem
                                        key={option}
                                        selected={option === menu}
                                        onClick={() => {
                                            setMenu(option);
                                            setMenuAnchor(null);
                                        }}
                                    >
                                        {option}
                                    </MenuItem>
                                ))}
                            </Menu>
                        </Box>
                        {gallery}
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
                    width: rightCollapsed ? 40 : 320,
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
