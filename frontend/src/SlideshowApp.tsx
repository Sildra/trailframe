import { useCallback, useEffect, useState } from "react";
import { Box, CircularProgress } from "@mui/material";
import SlideshowMenuPage from "./pages/SlideshowMenuPage";
import SlideshowPage, { type SlideshowSource } from "./pages/SlideshowPage";
import { parseMenuSection, type MenuSection } from "./lib/slideshowSections";
import { api } from "./api/client";
import type { SlideshowOption } from "./pages/SlideshowPage";

function parseOption(search: URLSearchParams, key: string): SlideshowOption {
    return search.get(key) === "hide" ? "hide" : "full";
}

function parseSource(search: URLSearchParams): SlideshowSource | null {
    const activityParam = search.get("activity");

    if (activityParam !== null) {
        const activityId = Number(activityParam);

        if (Number.isInteger(activityId) && activityId > 0) {
            return {
                kind: "activity",
                activity: { id: activityId, photos: 0 },
                controls: parseOption(search, "controls"),
                map: parseOption(search, "map"),
            };
        }

        return null;
    }

    const photoIds = (search.get("photos") ?? "")
        .split(",")
        .map((value) => Number(value.trim()))
        .filter((value) => Number.isInteger(value) && value > 0);

    if (photoIds.length === 0) {
        return null;
    }

    return {
        kind: "group",
        name: search.get("name") || "Slideshow",
        photoIds,
        thumbnails: search.get("thumbs") === "1",
        controls: parseOption(search, "controls"),
        map: parseOption(search, "map"),
    };
}

function sourceKey(source: SlideshowSource): string {
    return source.kind === "activity"
        ? `activity:${source.activity.id}`
        : `group:${source.name}`;
}

function buildQuery(search: URLSearchParams): Record<string, unknown> {
    const query: Record<string, unknown> = {};
    const startDate = search.get("start_date");
    const endDate = search.get("end_date");
    const group = search.get("group");
    const location = search.get("location");
    const tags = search.get("tags");

    if (startDate) {
        query.start_date = startDate;
    }

    if (endDate) {
        query.end_date = endDate;
    }

    if (group) {
        query.group = group;
    }

    if (location) {
        query.location = location;
    }

    if (tags) {
        query.tags = tags
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean);
    }

    if (search.get("favorites") === "1") {
        query.favorites = true;
    }

    if (search.get("randomize") === "1") {
        query.randomize = true;
    }

    return query;
}

export default function SlideshowApp() {
    const [initialParams] = useState(() => new URLSearchParams(window.location.search));
    const [source, setSource] = useState<SlideshowSource | null>(() => parseSource(initialParams));
    const [section, setSection] = useState<MenuSection>(() => parseMenuSection(initialParams.get("section")));
    const [resolving, setResolving] = useState(
        () => initialParams.get("start") === "1" && parseSource(initialParams) === null,
    );

    useEffect(() => {
        if (initialParams.get("start") !== "1" || parseSource(initialParams) !== null) {
            return;
        }

        let cancelled = false;

        api.GET("/api/photos/custom", { params: { query: buildQuery(initialParams) } })
            .then(({ data, error }) => {
                if (cancelled) {
                    return;
                }

                if (!error && data && data.length > 0) {
                    setSource({
                        kind: "group",
                        name: initialParams.get("name") || "Custom",
                        photoIds: data,
                        thumbnails: initialParams.get("thumbs") === "1",
                        controls: parseOption(initialParams, "controls"),
                        map: parseOption(initialParams, "map"),
                    });
                }
            })
            .catch(() => {})
            .finally(() => {
                if (!cancelled) {
                    setResolving(false);
                }
            });

        return () => {
            cancelled = true;
        };
    }, [initialParams]);

    const start = useCallback((next: SlideshowSource) => {
        setSource(next);
    }, []);

    const changeSection = useCallback((next: MenuSection) => {
        setSection(next);
    }, []);

    const exit = useCallback(() => {
        setSource(null);
    }, []);

    if (source !== null) {
        return (
            <Box sx={{ height: "100svh", display: "flex", flexDirection: "column", overflow: "hidden" }}>
                <SlideshowPage key={sourceKey(source)} source={source} onExit={exit} />
            </Box>
        );
    }

    if (resolving) {
        return (
            <Box sx={{ height: "100svh", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <CircularProgress />
            </Box>
        );
    }

    return (
        <Box sx={{ height: "100svh", display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <SlideshowMenuPage section={section} onSectionChange={changeSection} onStartSlideshow={start} />
        </Box>
    );
}
