import { useEffect, useMemo, useRef, useState } from "react";
import {
    Alert,
    Box,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    IconButton,
    Link,
    Typography,
} from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import CloseIcon from "@mui/icons-material/Close";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { splitSlides } from "../lib/markdownSlides";

const MARKDOWN_COMPONENTS: Components = {
    h1: ({ children }) => (
        <Typography variant="h4" component="h1" gutterBottom>
            {children}
        </Typography>
    ),
    h2: ({ children }) => (
        <Typography variant="h5" component="h2" gutterBottom sx={{ mt: 1 }}>
            {children}
        </Typography>
    ),
    h3: ({ children }) => (
        <Typography variant="h6" component="h3" gutterBottom>
            {children}
        </Typography>
    ),
    h4: ({ children }) => (
        <Typography variant="subtitle1" component="h4" gutterBottom sx={{ fontWeight: 600 }}>
            {children}
        </Typography>
    ),
    p: ({ children }) => (
        <Typography variant="body1" component="p" sx={{ mb: 1.5 }}>
            {children}
        </Typography>
    ),
    a: ({ href, children }) => (
        <Link href={href} target="_blank" rel="noreferrer">
            {children}
        </Link>
    ),
};

export type SlidePosition = "first" | "last";

interface MarkdownSlidesDialogProps {
    open: boolean;
    onClose: () => void;
    title: string;
    markdown: string | null;
    loading?: boolean;
    error?: string | null;
    initialSlide?: SlidePosition;
}

export default function MarkdownSlidesDialog({
    open,
    onClose,
    title,
    markdown,
    loading = false,
    error = null,
    initialSlide = "first",
}: MarkdownSlidesDialogProps) {
    const slides = useMemo(() => (markdown ? splitSlides(markdown) : []), [markdown]);
    const [slide, setSlide] = useState<number | null>(null);
    const contentRef = useRef<HTMLDivElement>(null);

    const initialIndex = initialSlide === "last" ? Math.max(slides.length - 1, 0) : 0;
    const currentSlide =
        slides.length === 0 ? 0 : Math.min(Math.max(slide ?? initialIndex, 0), slides.length - 1);
    const showLoading = loading || (markdown === null && error === null);

    useEffect(() => {
        contentRef.current?.scrollTo({ top: 0 });
    }, [currentSlide]);

    useEffect(() => {
        if (!open) {
            return;
        }

        const handleKeyDown = (event: KeyboardEvent) => {
            if (slides.length === 0) {
                return;
            }

            if (event.key === "ArrowLeft") {
                event.preventDefault();
                setSlide((value) => Math.max(0, (value ?? initialIndex) - 1));
            } else if (event.key === "ArrowRight") {
                event.preventDefault();
                setSlide((value) => Math.min(slides.length - 1, (value ?? initialIndex) + 1));
            }
        };

        window.addEventListener("keydown", handleKeyDown);

        return () => {
            window.removeEventListener("keydown", handleKeyDown);
        };
    }, [open, initialIndex, slides.length]);

    const goTo = (index: number) => {
        setSlide(Math.max(0, Math.min(slides.length - 1, index)));
    };

    return (
        <Dialog
            open={open}
            onClose={onClose}
            fullWidth
            maxWidth="lg"
            sx={{ "& .MuiDialog-paper": { height: "min(88vh, 960px)" } }}
        >
            <DialogTitle sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                <Typography variant="h6" component="span" sx={{ flex: 1 }}>
                    {title}
                </Typography>
                <IconButton onClick={onClose} size="small" aria-label="Close document">
                    <CloseIcon />
                </IconButton>
            </DialogTitle>
            <DialogContent dividers ref={contentRef}>
                {showLoading ? (
                    <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
                        <CircularProgress />
                    </Box>
                ) : error ? (
                    <Alert severity="error">{error}</Alert>
                ) : (
                    <Box
                        sx={{
                            "& ul, & ol": { mt: 0, mb: 2, pl: 3 },
                            "& li": { mb: 0.5 },
                            "& code": {
                                fontFamily: "monospace",
                                bgcolor: "action.hover",
                                px: 0.5,
                                py: 0.25,
                                borderRadius: 0.5,
                                fontSize: "0.9em",
                            },
                            "& pre": {
                                bgcolor: "action.hover",
                                p: 1.5,
                                borderRadius: 1,
                                overflowX: "auto",
                                "& code": { bgcolor: "transparent", p: 0 },
                            },
                            "& blockquote": {
                                borderLeft: 3,
                                borderColor: "divider",
                                pl: 2,
                                my: 1,
                                color: "text.secondary",
                            },
                            "& table": { borderCollapse: "collapse", width: "100%", mb: 2 },
                            "& th, & td": {
                                border: 1,
                                borderColor: "divider",
                                px: 1,
                                py: 0.5,
                                textAlign: "left",
                            },
                            "& th": { bgcolor: "action.hover", fontWeight: 600 },
                            "& img": { maxWidth: "100%", borderRadius: 1 },
                        }}
                    >
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                            {slides[currentSlide] ?? ""}
                        </ReactMarkdown>
                    </Box>
                )}
            </DialogContent>
            <DialogActions sx={{ justifyContent: "space-between", px: 2 }}>
                <IconButton
                    onClick={() => goTo(currentSlide - 1)}
                    disabled={slides.length === 0 || currentSlide === 0}
                    aria-label="Previous slide"
                >
                    <ChevronLeftIcon />
                </IconButton>
                <Typography variant="body2" color="text.secondary">
                    {slides.length > 0 ? `${currentSlide + 1} / ${slides.length}` : ""}
                </Typography>
                <IconButton
                    onClick={() => goTo(currentSlide + 1)}
                    disabled={slides.length === 0 || currentSlide >= slides.length - 1}
                    aria-label="Next slide"
                >
                    <ChevronRightIcon />
                </IconButton>
            </DialogActions>
        </Dialog>
    );
}
