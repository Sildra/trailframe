import { useEffect, useState } from "react";
import {
    Autocomplete,
    Box,
    Button,
    Chip,
    FormControlLabel,
    Stack,
    Switch,
    TextField,
    Typography,
} from "@mui/material";
import ShuffleIcon from "@mui/icons-material/Shuffle";
import StarIcon from "@mui/icons-material/Star";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";

type PhotoGroupSummary = components["schemas"]["PhotoGroupSummary"];

interface CustomSlideshowMenuProps {
    onStart: (name: string, photoIds: number[], useThumbnails: boolean) => void;
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
    const [loading, setLoading] = useState(false);

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

    const handleStart = async () => {
        setLoading(true);

        try {
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

            const { data, error } = await api.GET("/api/photos/custom", { params: { query: params } });

            if (!error && data && data.length > 0) {
                const label = buildLabel();
                onStart(label, data, useThumbnails);
            }
        } finally {
            setLoading(false);
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

            <Button variant="contained" onClick={handleStart} disabled={loading}>
                Start slideshow
            </Button>
        </Stack>
    );
}
