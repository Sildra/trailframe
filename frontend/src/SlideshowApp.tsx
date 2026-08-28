import { useCallback, useState } from "react";
import { Box } from "@mui/material";
import SlideshowMenuPage from "./pages/SlideshowMenuPage";
import SlideshowPage, { type SlideshowSource } from "./pages/SlideshowPage";
import { parseMenuSection, type MenuSection } from "./lib/slideshowSections";

function parseSource(search: URLSearchParams): SlideshowSource | null {
    const activityParam = search.get("activity");

    if (activityParam !== null) {
        const activityId = Number(activityParam);

        if (Number.isInteger(activityId) && activityId > 0) {
            return { kind: "activity", activity: { id: activityId, photos: 0 } };
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
    };
}

function sourceKey(source: SlideshowSource): string {
    return source.kind === "activity"
        ? `activity:${source.activity.id}`
        : `group:${source.name}`;
}

export default function SlideshowApp() {
    const [initialParams] = useState(() => new URLSearchParams(window.location.search));
    const [source, setSource] = useState<SlideshowSource | null>(() => parseSource(initialParams));
    const [section, setSection] = useState<MenuSection>(() => parseMenuSection(initialParams.get("section")));

    const start = useCallback((next: SlideshowSource) => {
        setSource(next);
    }, []);

    const changeSection = useCallback((next: MenuSection) => {
        setSection(next);
    }, []);

    const exit = useCallback(() => {
        setSource(null);
    }, []);

    return (
        <Box sx={{ height: "100svh", display: "flex", flexDirection: "column", overflow: "hidden" }}>
            {source === null ? (
                <SlideshowMenuPage section={section} onSectionChange={changeSection} onStartSlideshow={start} />
            ) : (
                <SlideshowPage key={sourceKey(source)} source={source} onExit={exit} />
            )}
        </Box>
    );
}
