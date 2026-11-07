import { useCallback, useEffect, useState } from "react";
import { AppBar, Box, IconButton, Menu, MenuItem, Tab, Tabs, Toolbar } from "@mui/material";
import HelpOutlinedIcon from "@mui/icons-material/HelpOutlined";
import GalleryPage from "./pages/GalleryPage";
import ActivitiesPage from "./pages/ActivitiesPage";
import SlideshowMenuPage from "./pages/SlideshowMenuPage";
import SlideshowPage, { type SlideshowSource } from "./pages/SlideshowPage";
import ParametersPage from "./pages/ConfigurationPage";
import TagsPage from "./pages/TagsPage";
import ToolsPage from "./pages/ToolsPage";
import EventBar from "./components/EventBar";
import MarkdownSlidesDialog, { type SlidePosition } from "./components/MarkdownSlidesDialog";
import { EventProvider } from "./events/EventProvider";
import { api } from "./api/client";
import { parseMenuSection, type MenuSection } from "./lib/slideshowSections";
import type { components } from "./api/generated/schema";

type Page = "gallery" | "activities" | "slideshow" | "configuration" | "tags" | "tools";

type DocumentName = "hardware" | "tutorial" | "whats-new";

type Activity = components["schemas"]["ActivitySummary"];

const PAGES: Array<{ id: Page; label: string }> = [
    { id: "gallery", label: "Gallery" },
    { id: "activities", label: "Activities" },
    { id: "slideshow", label: "Slideshow" },
    { id: "tags", label: "Tags" },
    { id: "tools", label: "Tools" },
    { id: "configuration", label: "Configuration" },
];

const DOCUMENTS: Record<DocumentName, string> = {
    hardware: "Hardware & performance",
    tutorial: "Tutorial",
    "whats-new": "What's new",
};

const SEEN_VERSION_KEY = "trailframe.seenVersion";

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
    const [helpAnchor, setHelpAnchor] = useState<HTMLElement | null>(null);
    const [openDocument, setOpenDocument] = useState<DocumentName | null>(null);
    const [documentPosition, setDocumentPosition] = useState<SlidePosition>("first");
    const [markSeenOnClose, setMarkSeenOnClose] = useState(false);
    const [appVersion, setAppVersion] = useState<string | null>(null);
    const [documents, setDocuments] = useState<Record<string, string>>({});
    const [documentErrors, setDocumentErrors] = useState<Record<string, string>>({});

    const pageIndex = PAGES.findIndex(({ id }) => id === page);
    const loadedDocument = openDocument ? documents[openDocument] : undefined;
    const documentError = openDocument ? documentErrors[openDocument] : undefined;

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/about/version")
            .then(({ data, error }) => {
                if (cancelled || error || !data) {
                    return;
                }

                setAppVersion(data.version);

                const seenVersion = window.localStorage.getItem(SEEN_VERSION_KEY);

                if (seenVersion === null) {
                    window.localStorage.setItem(SEEN_VERSION_KEY, data.version);
                } else if (seenVersion !== data.version) {
                    setDocumentPosition("last");
                    setMarkSeenOnClose(true);
                    setOpenDocument("whats-new");
                }
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        if (!openDocument || loadedDocument !== undefined || documentError !== undefined) {
            return;
        }

        const name = openDocument;
        let cancelled = false;

        api.GET("/api/docs/{name}", { params: { path: { name } } })
            .then(({ data, error }) => {
                if (cancelled) {
                    return;
                }

                if (error || !data) {
                    setDocumentErrors((previous) => ({
                        ...previous,
                        [name]: "The document could not be loaded.",
                    }));
                    return;
                }

                setDocuments((previous) => ({ ...previous, [name]: data.content }));
            })
            .catch(() => {
                if (!cancelled) {
                    setDocumentErrors((previous) => ({
                        ...previous,
                        [name]: "The document could not be loaded.",
                    }));
                }
            });

        return () => {
            cancelled = true;
        };
    }, [openDocument, loadedDocument, documentError]);

    const closeDocument = useCallback(() => {
        if (markSeenOnClose && appVersion !== null) {
            window.localStorage.setItem(SEEN_VERSION_KEY, appVersion);
        }

        setOpenDocument(null);
        setMarkSeenOnClose(false);
    }, [appVersion, markSeenOnClose]);

    const showDocument = useCallback((name: DocumentName, position: SlidePosition = "first") => {
        setHelpAnchor(null);
        setDocumentPosition(position);
        setMarkSeenOnClose(name === "whats-new" && position === "last");
        setOpenDocument(name);
    }, []);

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
                        <Toolbar variant="dense" disableGutters sx={{ px: 1, minWidth: 0 }}>
                            <Tabs
                                value={pageIndex}
                                variant="scrollable"
                                scrollButtons="auto"
                                sx={{ flex: 1, minWidth: 0 }}
                                onChange={(_event, value) => {
                                    setPage(PAGES[value as number].id);
                                }}
                            >
                                {PAGES.map(({ id, label }) => (
                                    <Tab key={id} label={label} sx={{ flexShrink: 0 }} />
                                ))}
                            </Tabs>
                            <IconButton
                                size="small"
                                aria-label="Help"
                                sx={{ flexShrink: 0 }}
                                onClick={(event) => setHelpAnchor(event.currentTarget)}
                            >
                                <HelpOutlinedIcon />
                            </IconButton>
                            <Menu
                                anchorEl={helpAnchor}
                                open={helpAnchor !== null}
                                onClose={() => setHelpAnchor(null)}
                            >
                                <MenuItem onClick={() => showDocument("tutorial")}>Tutorial</MenuItem>
                                <MenuItem onClick={() => showDocument("hardware")}>Hardware & performance</MenuItem>
                                <MenuItem onClick={() => showDocument("whats-new")}>What's new</MenuItem>
                            </Menu>
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
                        {page === "tags" && <TagsPage />}
                        {page === "configuration" && <ParametersPage />}
                        <EventBar />
                    </Box>
                )}
            </Box>
            <MarkdownSlidesDialog
                key={openDocument ?? "closed"}
                open={openDocument !== null}
                onClose={closeDocument}
                title={openDocument ? DOCUMENTS[openDocument] : ""}
                markdown={loadedDocument ?? null}
                loading={openDocument !== null && loadedDocument === undefined && documentError === undefined}
                error={documentError ?? null}
                initialSlide={documentPosition}
            />
        </EventProvider>
    );
}
