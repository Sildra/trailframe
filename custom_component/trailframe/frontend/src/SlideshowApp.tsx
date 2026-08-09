import { useCallback, useState } from "react";
import { Box } from "@mui/material";
import SlideshowMenuPage from "./pages/SlideshowMenuPage";
import SlideshowPage, { type SlideshowSource } from "./pages/SlideshowPage";
import { orderedSearch, parseMenuSection, withMenuSection, type MenuSection } from "./lib/slideshowSections";

const ENTRY_PATH = "/slideshow.html";

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

function sourceSearch(source: SlideshowSource, section: MenuSection): string {
    const params = new URLSearchParams();

    if (source.kind === "activity") {
        params.set("activity", String(source.activity.id ?? ""));
    } else {
        params.set("photos", source.photoIds.join(","));
        params.set("name", source.name);

        if (source.thumbnails) {
            params.set("thumbs", "1");
        }
    }

    params.set("section", section);

    return orderedSearch(params);
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
        window.history.replaceState(null, "", `${ENTRY_PATH}?${sourceSearch(next, section)}`);
        setSource(next);
    }, [section]);

    const changeSection = useCallback((next: MenuSection) => {
        window.history.replaceState(null, "", `${ENTRY_PATH}${withMenuSection(new URLSearchParams(window.location.search), next)}`);
        setSection(next);
    }, []);

    const exit = useCallback(() => {
        window.history.replaceState(null, "", `${ENTRY_PATH}${withMenuSection(new URLSearchParams(window.location.search), section)}`);
        setSource(null);
    }, [section]);

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
