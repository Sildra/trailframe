import { useState } from "react";
import { AppBar, Box, Tab, Tabs, Toolbar } from "@mui/material";
import GalleryPage from "./pages/GalleryPage";
import ActivitiesPage from "./pages/ActivitiesPage";
import SlideshowMenuPage from "./pages/SlideshowMenuPage";
import SlideshowPage, { type SlideshowSource } from "./pages/SlideshowPage";
import ParametersPage from "./pages/ConfigurationPage";
import ToolsPage from "./pages/ToolsPage";
import EventBar from "./components/EventBar";
import { EventProvider } from "./events/EventProvider";
import { parseMenuSection, type MenuSection } from "./lib/slideshowSections";
import type { components } from "./api/generated/schema";

type Page = "gallery" | "activities" | "slideshow" | "configuration" | "tools";

type Activity = components["schemas"]["ActivitySummary"];

const PAGES: Array<{ id: Page; label: string }> = [
    { id: "gallery", label: "Gallery" },
    { id: "activities", label: "Activities" },
    { id: "slideshow", label: "Slideshow" },
    { id: "tools", label: "Tools" },
    { id: "configuration", label: "Configuration" },
];

function initialPage(): Page {
    const value = new URLSearchParams(window.location.search).get("page");

    return PAGES.some(({ id }) => id === value) ? (value as Page) : "gallery";
}

export default function App() {
    const [initialParams] = useState(() => new URLSearchParams(window.location.search));
    const [page, setPage] = useState<Page>(initialPage);
    const [slideshowSection, setSlideshowSection] = useState<MenuSection>(() =>
        parseMenuSection(initialParams.get("section")),
    );
    const [slideshowSource, setSlideshowSource] = useState<SlideshowSource | null>(null);

    const pageIndex = PAGES.findIndex(({ id }) => id === page);

    function changeSlideshowSection(section: MenuSection) {
        setSlideshowSection(section);
    }

    function startSlideshow(source: SlideshowSource) {
        setSlideshowSource(source);
    }

    function startActivitySlideshow(activity: Activity) {
        startSlideshow({ kind: "activity", activity });
    }

    return (
        <EventProvider>
            <Box sx={{ height: "100svh", display: "flex", flexDirection: "column", overflow: "hidden" }}>
                {slideshowSource === null && (
                    <AppBar
                        position="static"
                        color="default"
                        elevation={0}
                        sx={{ borderBottom: 1, borderColor: "divider" }}
                    >
                        <Toolbar variant="dense" disableGutters sx={{ px: 1 }}>
                            <Tabs
                                value={pageIndex}
                                onChange={(_event, value) => {
                                    setPage(PAGES[value as number].id);
                                }}
                            >
                                {PAGES.map(({ id, label }) => (
                                    <Tab key={id} label={label} />
                                ))}
                            </Tabs>
                        </Toolbar>
                    </AppBar>
                )}
                {slideshowSource !== null ? (
                    <SlideshowPage
                        key={
                            slideshowSource.kind === "activity"
                                ? `activity:${slideshowSource.activity.id}`
                                : `group:${slideshowSource.name}`
                        }
                        source={slideshowSource}
                        onExit={() => setSlideshowSource(null)}
                    />
                ) : (
                    <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                        {page === "gallery" && <GalleryPage />}
                        {page === "activities" && (
                            <ActivitiesPage onStartSlideshow={startActivitySlideshow} />
                        )}
                        {page === "slideshow" && (
                            <SlideshowMenuPage
                                section={slideshowSection}
                                onSectionChange={changeSlideshowSection}
                                onStartSlideshow={startSlideshow}
                            />
                        )}
                        {page === "tools" && <ToolsPage />}
                        {page === "configuration" && <ParametersPage />}
                        <EventBar />
                    </Box>
                )}
            </Box>
        </EventProvider>
    );
}
