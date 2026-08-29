import { useEffect, useState } from "react";
import {
    Autocomplete,
    Box,
    Button,
    Chip,
    FormControlLabel,
    IconButton,
    Stack,
    Switch,
    TextField,
    Tooltip,
    Typography,
} from "@mui/material";
import ShuffleIcon from "@mui/icons-material/Shuffle";
import StarIcon from "@mui/icons-material/Star";
import CheckIcon from "@mui/icons-material/Check";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import { orderedSearch } from "../lib/slideshowSections";
import type { SlideshowOption } from "../pages/SlideshowPage";

type PhotoGroupSummary = components["schemas"]["PhotoGroupSummary"];

interface CustomSlideshowMenuProps {
    onStart: (
        name: string,
        photoIds: number[],
        useThumbnails: boolean,
        controls: SlideshowOption,
        map: SlideshowOption,
    ) => void;
}

export default function CustomSlideshowMenu({ onStart }: CustomSlideshowMenuProps) {
    const [groups, setGroups] = useState<PhotoGroupSummary[]>([]);
    const [startDate, setStartDate] = useState("");
    const [endDate, setEndDate] = useState("");
    const [selectedGroup, setSelectedGroup] = useState<PhotoGroupSummary | null>(null);
    const [location, setLocation] = useState("");
    const [tags, setTags] = useState<string[]>([]);
    const [tagInput, setTagInput] = useState("");
    const [randomize, setRandomize] = useState(false);
    const [favoritesOnly, setFavoritesOnly] = useState(false);
    const [useThumbnails, setUseThumbnails] = useState(false);
    const [controls, setControls] = useState<SlideshowOption>("full");
    const [map, setMap] = useState<SlideshowOption>("full");
    const [loading, setLoading] = useState(false);
    const [copied, setCopied] = useState(false);

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/photos/groups")
            .then(({ data, error }) => {
                if (!cancelled && !error && data) {
                    setGroups(data);
                }
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, []);

    const handleGroupChange = (_: unknown, value: PhotoGroupSummary | null) => {
        setSelectedGroup(value);

        if (value) {
            setStartDate(value.start_date ?? "");
            setEndDate(value.end_date ?? "");
        }
    };

    const buildParams = (): Record<string, unknown> => {
        const params: Record<string, unknown> = {};

        if (startDate) {
            params.start_date = startDate;
        }

        if (endDate) {
            params.end_date = endDate;
        }

        if (selectedGroup) {
            params.group = selectedGroup.name;
        }

        if (location) {
            params.location = location;
        }

        if (tags.length > 0) {
            params.tags = tags;
        }

        if (favoritesOnly) {
            params.favorites = true;
        }

        if (randomize) {
            params.randomize = true;
        }

        return params;
    };

    const fetchPhotoIds = async (): Promise<number[]> => {
        const { data, error } = await api.GET("/api/photos/custom", {
            params: { query: buildParams() },
        });

        return !error && data ? data : [];
    };

    const handleStart = async () => {
        setLoading(true);

        try {
            const photoIds = await fetchPhotoIds();

            if (photoIds.length > 0) {
                const label = buildLabel();
                onStart(label, photoIds, useThumbnails, controls, map);
            }
        } finally {
            setLoading(false);
        }
    };

    const buildSlideshowUrl = (): string => {
        const params = new URLSearchParams();
        params.set("section", "custom");
        params.set("start", "1");
        params.set("name", buildLabel());

        for (const [key, value] of Object.entries(buildParams())) {
            if (value === true) {
                params.set(key, "1");
            } else if (Array.isArray(value)) {
                params.set(key, value.join(","));
            } else if (value) {
                params.set(key, String(value));
            }
        }

        if (useThumbnails) {
            params.set("thumbs", "1");
        }

        if (controls !== "full") {
            params.set("controls", controls);
        }

        if (map !== "full") {
            params.set("map", map);
        }

        return `./slideshow.html${orderedSearch(params)}`;
    };

    const handleCopyUrl = async () => {
        try {
            await navigator.clipboard.writeText(buildSlideshowUrl());
            setCopied(true);
            window.setTimeout(() => setCopied(false), 2000);
        } catch {
            // clipboard write can fail (e.g. insecure context or denied permission)
        }
    };

    const buildLabel = () => {
        const parts: string[] = [];

        if (selectedGroup) {
            parts.push(selectedGroup.name);
        } else if (startDate || endDate) {
            parts.push(`${startDate ?? "..."} → ${endDate ?? "..."}`);
        }

        if (location) {
            parts.push(location);
        }

        if (tags.length > 0) {
            parts.push(tags.join(", "));
        }

        if (favoritesOnly) {
            parts.push("favorites");
        }

        if (useThumbnails) {
            parts.push("thumbnails");
        }

        if (randomize) {
            parts.push("shuffled");
        }

        return parts.length > 0 ? parts.join(" · ") : "Custom";
    };

    const handleTagKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
        if (event.key === "Enter" && tagInput.trim()) {
            event.preventDefault();
            const newTag = tagInput.trim();

            if (!tags.includes(newTag)) {
                setTags([...tags, newTag]);
            }

            setTagInput("");
        }
    };

    const handleTagDelete = (tag: string) => {
        setTags(tags.filter((t) => t !== tag));
    };

    return (
        <Stack spacing={2} sx={{ maxWidth: 400 }}>
            <Typography variant="subtitle2">Group</Typography>
            <Autocomplete
                options={groups}
                getOptionLabel={(option) => option.name}
                value={selectedGroup}
                onChange={handleGroupChange}
                renderInput={(params) => <TextField {...params} label="Select group" size="small" />}
                isOptionEqualToValue={(option, value) => option.name === value.name}
            />

            <Typography variant="subtitle2">Date range</Typography>
            <Stack direction="row" spacing={1}>
                <TextField
                    label="Start date"
                    type="date"
                    size="small"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    slotProps={{ inputLabel: { shrink: true } }}
                    sx={{ flex: 1 }}
                />
                <TextField
                    label="End date"
                    type="date"
                    size="small"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    slotProps={{ inputLabel: { shrink: true } }}
                    sx={{ flex: 1 }}
                />
            </Stack>

            <Typography variant="subtitle2">Location</Typography>
            <TextField
                label="Filter by location"
                size="small"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="e.g. South Australia"
            />

            <Typography variant="subtitle2">Tags</Typography>
            <TextField
                label="Add tags"
                size="small"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={handleTagKeyDown}
                placeholder="Type and press Enter"
            />
            {tags.length > 0 && (
                <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                    {tags.map((tag) => (
                        <Chip key={tag} label={tag} size="small" onDelete={() => handleTagDelete(tag)} />
                    ))}
                </Box>
            )}

            <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap" }}>
                <Chip
                    size="small"
                    icon={<StarIcon />}
                    label="Favorites only"
                    clickable
                    color={favoritesOnly ? "primary" : "default"}
                    variant={favoritesOnly ? "filled" : "outlined"}
                    onClick={() => setFavoritesOnly((value) => !value)}
                />
                <Chip
                    size="small"
                    label="Use thumbnails"
                    clickable
                    color={useThumbnails ? "primary" : "default"}
                    variant={useThumbnails ? "filled" : "outlined"}
                    onClick={() => setUseThumbnails((value) => !value)}
                />
                <Chip
                    size="small"
                    label={controls === "full" ? "Full controls" : "Hide controls"}
                    clickable
                    color={controls === "full" ? "primary" : "default"}
                    variant={controls === "full" ? "filled" : "outlined"}
                    onClick={() => setControls((value) => (value === "hide" ? "full" : "hide"))}
                />
                <Chip
                    size="small"
                    label={map === "full" ? "Full map" : "Hide map"}
                    clickable
                    color={map === "full" ? "primary" : "default"}
                    variant={map === "full" ? "filled" : "outlined"}
                    onClick={() => setMap((value) => (value === "hide" ? "full" : "hide"))}
                />
            </Box>

            <FormControlLabel
                control={
                    <Switch checked={randomize} onChange={(e) => setRandomize(e.target.checked)} />
                }
                label={
                    <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                        <ShuffleIcon fontSize="small" />
                        Randomize
                    </Box>
                }
            />

            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                <Button variant="contained" onClick={handleStart} disabled={loading} sx={{ flex: 1 }}>
                    Start slideshow
                </Button>
                <Tooltip title={copied ? "Copied!" : "Copy slideshow URL"}>
                    <IconButton
                        aria-label="Copy slideshow URL"
                        size="small"
                        color="primary"
                        onClick={handleCopyUrl}
                        disabled={loading || copied}
                    >
                        {copied ? <CheckIcon fontSize="small" /> : <ContentCopyIcon fontSize="small" />}
                    </IconButton>
                </Tooltip>
            </Box>
        </Stack>
    );
}
