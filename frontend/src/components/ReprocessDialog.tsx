import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Alert,
    Box,
    Button,
    Chip,
    CircularProgress,
    Dialog,
    FormControlLabel,
    MenuItem,
    Radio,
    RadioGroup,
    Slider,
    Switch,
    TextField,
    Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import PhotoLibraryIcon from "@mui/icons-material/PhotoLibrary";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import { SIDE_PANEL_WIDTH } from "../lib/layout";
import {
    cloneReprocessOptions,
    isEdited,
    normalizeReprocessOptions,
    sortPhotosByTime,
    type NormalizationMode,
} from "../lib/multiEdit";
import { normalizeProcessing, parseLine, parsePoint } from "../lib/processing";
import { buildPreview, effectiveAngle } from "../lib/preview";
import {
    MAX_MANUAL_ANGLE,
    MAX_TARGETS,
    MAX_TARGET_SIZE,
    MIN_TARGET_SIZE,
    defaultReprocessOptions,
    parseAngle,
    toReprocessPayload,
    validateOptions,
    type CropMode,
    type ReprocessOptions,
    type TiltMode,
} from "../lib/reprocess";
import ProcessingPreview, { type PreviewCorrections } from "./ProcessingPreview";
import ThumbnailGallery from "./ThumbnailGallery";

type Photo = components["schemas"]["PhotoDetail"];
type SimilarCandidate = components["schemas"]["SimilarPhoto"];
type WindowUnit = "minute" | "hour" | "day";

interface ReprocessDialogProps {
    photo: Photo;
    onClose: () => void;
    onUpdated: (photo: Photo) => void;
}

interface PreviewImage {
    photoId: number;
    url: string;
    width: number;
    height: number;
}

interface PreviewError {
    photoId: number;
    message: string;
}

interface SaveItem {
    photo: Photo;
    options: ReprocessOptions;
}

function formatAngle(value: number): string {
    return String(Math.round(value * 100) / 100);
}

function errorMessage(error: unknown, fallback: string): string {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    return typeof detail === "string" ? detail : fallback;
}

function parseWindow(text: string): { seconds: number; value: number; unit: WindowUnit } | null {
    const match = /^\s*(\d+(?:\.\d+)?)\s*(minutes?|mins?|m|hours?|hrs?|h|days?|d)\s*$/i.exec(text);

    if (!match) {
        return null;
    }

    const value = Number(match[1]);

    if (!Number.isFinite(value) || value <= 0) {
        return null;
    }

    const short = match[2].toLowerCase();
    const unit: WindowUnit = short.startsWith("m") ? "minute" : short.startsWith("h") ? "hour" : "day";
    const factor = unit === "minute" ? 60 : unit === "hour" ? 3600 : 86400;
    return { seconds: Math.max(1, Math.min(30 * 24 * 3600, Math.round(value * factor))), value, unit };
}

function formatWindow(value: number, unit: WindowUnit): string {
    const label = unit === "minute" ? "min" : unit === "hour" ? "h" : "d";
    return `${value} ${label}`;
}

function omitIds<T>(record: Record<number, T>, ids: number[]): Record<number, T> {
    const next = { ...record };

    for (const id of ids) {
        delete next[id];
    }

    return next;
}

function DetailRows({ details }: { details: Record<string, string> }) {
    return (
        <Box sx={{ display: "flex", flexDirection: "column", gap: "2px" }}>
            {Object.entries(details).map(([label, value]) => (
                <Box key={label} sx={{ display: "flex", justifyContent: "space-between", gap: 1 }}>
                    <Typography variant="caption" color="text.secondary">
                        {label}
                    </Typography>
                    <Typography variant="caption" sx={{ textAlign: "right" }}>
                        {value}
                    </Typography>
                </Box>
            ))}
        </Box>
    );
}

function SizeRow({ label, width, height }: { label: string; width: number; height: number }) {
    return (
        <Box sx={{ display: "flex", justifyContent: "space-between", gap: 1 }}>
            <Typography variant="caption" color="text.secondary">
                {label}
            </Typography>
            <Typography variant="caption">
                {width} × {height} px
            </Typography>
        </Box>
    );
}

function SliderRow({
    label,
    value,
    min,
    max,
    step,
    onChange,
    format,
}: {
    label: string;
    value: number;
    min: number;
    max: number;
    step: number;
    onChange: (value: number) => void;
    format?: (value: number) => string;
}) {
    return (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 0.25 }}>
            <Box sx={{ display: "flex", justifyContent: "space-between", gap: 1 }}>
                <Typography variant="caption" color="text.secondary">
                    {label}
                </Typography>
                <Typography variant="caption">{format ? format(value) : value}</Typography>
            </Box>
            <Slider
                size="small"
                min={min}
                max={max}
                step={step}
                value={value}
                onChange={(_, next) => onChange(next as number)}
            />
        </Box>
    );
}

function CorrectionAccordion({
    title,
    enabled,
    onEnabled,
    children,
}: {
    title: string;
    enabled: boolean;
    onEnabled: (value: boolean) => void;
    children: ReactNode;
}) {
    return (
        <Accordion disableGutters>
            <AccordionSummary
                expandIcon={<ExpandMoreIcon />}
                sx={{ fontWeight: 600, fontSize: 14, minHeight: 40 }}
            >
                <Box sx={{ display: "flex", alignItems: "center", gap: 1, width: "100%" }}>
                    <span>{title}</span>
                    <Box sx={{ flex: 1 }} />
                    <Switch
                        size="small"
                        checked={enabled}
                        onChange={(event) => onEnabled(event.target.checked)}
                        onClick={(event) => event.stopPropagation()}
                        slotProps={{ input: { "aria-label": `Enable ${title}` } }}
                    />
                </Box>
            </AccordionSummary>
            <AccordionDetails sx={{ display: "flex", flexDirection: "column", gap: 1.5 }}>{children}</AccordionDetails>
        </Accordion>
    );
}

type CorrectionKey =
    | "exposure"
    | "whiteBalance"
    | "contrast"
    | "localContrast"
    | "vibrance"
    | "noiseReduction"
    | "sharpening";

export default function ReprocessDialog({ photo, onClose, onUpdated }: ReprocessDialogProps) {
    const [optionsById, setOptionsById] = useState<Record<number, ReprocessOptions>>(() =>
        photo.id == null ? {} : { [photo.id]: defaultReprocessOptions(photo) },
    );
    const [angleById, setAngleById] = useState<Record<number, string>>(() =>
        photo.id == null ? {} : { [photo.id]: formatAngle(defaultReprocessOptions(photo).angle) },
    );
    const [newSize, setNewSize] = useState("");
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [preview, setPreview] = useState<PreviewImage | null>(null);
    const [previewError, setPreviewError] = useState<PreviewError | null>(null);
    const [activeId, setActiveId] = useState<number | null>(photo.id ?? null);
    const [windowText, setWindowText] = useState(() => formatWindow(30, "minute"));
    const [candidates, setCandidates] = useState<SimilarCandidate[]>([]);
    const [checkedIds, setCheckedIds] = useState<Set<number>>(() =>
        new Set(photo.id == null ? [] : [photo.id]),
    );
    const [normalizationMode, setNormalizationMode] = useState<NormalizationMode>("reference");
    const [finding, setFinding] = useState(photo.id != null);
    const [candidateError, setCandidateError] = useState<string | null>(null);
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [pendingSave, setPendingSave] = useState<SaveItem[]>([]);

    const optionsFor = (target: Photo): ReprocessOptions =>
        target.id != null ? (optionsById[target.id] ?? defaultReprocessOptions(target)) : defaultReprocessOptions(target);

    const windowSeconds = useMemo(() => parseWindow(windowText)?.seconds ?? 3600, [windowText]);

    const seedCandidate = useMemo<SimilarCandidate>(
        () => ({ photo, similar: true, score: 1, phash_distance: null, shared_objects: [] }),
        [photo],
    );
    const galleryCandidates = useMemo(
        () => (candidates.length > 0 ? candidates : [seedCandidate]),
        [candidates, seedCandidate],
    );
    const galleryPhotos = useMemo(
        () => sortPhotosByTime(galleryCandidates.map((candidate) => candidate.photo)),
        [galleryCandidates],
    );
    const activePhoto = useMemo(
        () => galleryPhotos.find((candidate) => candidate.id === activeId) ?? photo,
        [galleryPhotos, activeId, photo],
    );
    const activeOptions = optionsFor(activePhoto);
    const angleText =
        activePhoto.id != null ? (angleById[activePhoto.id] ?? formatAngle(activeOptions.angle)) : formatAngle(activeOptions.angle);
    const activePreview = preview?.photoId === activePhoto.id ? preview : null;
    const activePreviewError = previewError?.photoId === activePhoto.id ? previewError : null;

    const checkedCandidates = useMemo(
        () =>
            galleryCandidates.filter(
                (candidate) => candidate.photo.id != null && checkedIds.has(candidate.photo.id),
            ),
        [galleryCandidates, checkedIds],
    );
    const checkedPhotos = useMemo(
        () => sortPhotosByTime(checkedCandidates.map((candidate) => candidate.photo)),
        [checkedCandidates],
    );
    const multiEdit = checkedPhotos.length >= 2;
    const candidateIds = useMemo(
        () => galleryPhotos.map((candidate) => candidate.id).filter((id): id is number => id != null),
        [galleryPhotos],
    );
    const badges = useMemo(
        () =>
            Object.fromEntries(
                candidates
                    .filter((candidate) => candidate.photo.id != null)
                    .map((candidate) => [
                        candidate.photo.id as number,
                        candidate.similar ? `${Math.round(candidate.score * 100)}%` : "—",
                    ]),
            ),
        [candidates],
    );
    const editedIds = useMemo(() => {
        const ids = new Set<number>();

        for (const [key, options] of Object.entries(optionsById)) {
            const id = Number(key);
            const source = galleryPhotos.find((candidate) => candidate.id === id) ?? photo;

            if (source.id === id && isEdited(source, options)) {
                ids.add(id);
            }
        }

        return ids;
    }, [optionsById, galleryPhotos, photo]);

    // Keep edits on the displayed photo from being silently dropped when it is
    // not part of the checkbox selection.
    const savePhotos = useMemo(() => {
        if (!multiEdit || activePhoto.id == null) {
            return activePhoto.id == null ? [] : [activePhoto];
        }

        if (checkedPhotos.some((candidate) => candidate.id === activePhoto.id) || !editedIds.has(activePhoto.id)) {
            return checkedPhotos;
        }

        return sortPhotosByTime([...checkedPhotos, activePhoto]);
    }, [multiEdit, activePhoto, checkedPhotos, editedIds]);

    const corrections = useMemo<PreviewCorrections>(
        () => ({
            exposure: activeOptions.exposure,
            whiteBalance: activeOptions.whiteBalance,
            contrast: activeOptions.contrast,
            localContrast: activeOptions.localContrast,
            vibrance: activeOptions.vibrance,
            noiseReduction: activeOptions.noiseReduction,
            sharpening: activeOptions.sharpening,
        }),
        [
            activeOptions.exposure,
            activeOptions.whiteBalance,
            activeOptions.contrast,
            activeOptions.localContrast,
            activeOptions.vibrance,
            activeOptions.noiseReduction,
            activeOptions.sharpening,
        ],
    );

    const tilt = useMemo(() => {
        const step = normalizeProcessing(activePhoto.processing).find((entry) => entry.step === "tilt") ?? null;

        return {
            step,
            line: step ? parseLine(step.meta.line) : null,
            reference: step ? parsePoint(step.meta.reference_point) : null,
            detectedAngle: step ? parseAngle(step.summary) : null,
            applied: step?.meta.applied === true,
        };
    }, [activePhoto.processing]);

    useEffect(() => {
        if (activePhoto.id == null) {
            return;
        }

        const controller = new AbortController();
        let objectUrl: string | null = null;

        fetch(`./api/photos/${activePhoto.id}/preview?size=1200`, { signal: controller.signal })
            .then(async (response) => {
                if (!response.ok) {
                    throw new Error(`Preview unavailable (${response.status}).`);
                }

                const width = Number(response.headers.get("X-Original-Width"));
                const height = Number(response.headers.get("X-Original-Height"));

                if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
                    throw new Error("Preview dimensions are unavailable.");
                }

                const blob = await response.blob();

                if (controller.signal.aborted) {
                    return;
                }

                objectUrl = URL.createObjectURL(blob);
                setPreview({ photoId: activePhoto.id as number, url: objectUrl, width, height });
            })
            .catch((reason: unknown) => {
                if (!controller.signal.aborted) {
                    setPreviewError({
                        photoId: activePhoto.id as number,
                        message: reason instanceof Error ? reason.message : "Preview unavailable.",
                    });
                }
            });

        return () => {
            controller.abort();

            if (objectUrl) {
                URL.revokeObjectURL(objectUrl);
            }
        };
    }, [activePhoto.id]);

    const correction = effectiveAngle(
        activeOptions.tiltMode,
        activeOptions.angle,
        tilt.detectedAngle,
        tilt.applied,
    );
    const model = useMemo(() => {
        if (!activePreview) {
            return null;
        }

        return buildPreview(
            { width: activePreview.width, height: activePreview.height },
            { line: tilt.line, reference: tilt.reference, detectedAngle: tilt.detectedAngle },
            { angle: correction, cropMode: activeOptions.cropMode, target: activeOptions.main },
        );
    }, [activePreview, tilt, correction, activeOptions.cropMode, activeOptions.main]);

    const loadCandidates = useCallback(
        async (signal?: AbortSignal) => {
            if (photo.id == null) {
                return;
            }

            setFinding(true);
            setCandidateError(null);

            const { data, error: requestError } = await api.POST("/api/photos/similar-candidates", {
                body: {
                    photo_id: photo.id,
                    window_seconds: windowSeconds,
                    max_hamming: 12,
                    min_object_overlap: 0.4,
                },
                signal,
            });

            if (signal?.aborted) {
                return;
            }

            setFinding(false);

            if (requestError || !data) {
                setCandidateError(errorMessage(requestError, "Similarity search failed."));
                return;
            }

            setCandidates(data);
            const matched = data
                .filter((candidate) => candidate.similar && candidate.photo.id != null)
                .map((candidate) => candidate.photo.id as number);
            setCheckedIds(new Set(matched.includes(photo.id) ? matched : [photo.id, ...matched]));
        },
        [photo.id, windowSeconds],
    );
    const loadCandidatesRef = useRef(loadCandidates);

    useEffect(() => {
        loadCandidatesRef.current = loadCandidates;
    }, [loadCandidates]);

    useEffect(() => {
        if (photo.id == null) {
            return;
        }

        const controller = new AbortController();
        queueMicrotask(() => {
            void loadCandidatesRef.current(controller.signal);
        });

        return () => controller.abort();
    }, [photo.id]);

    const update = (patch: Partial<ReprocessOptions>) => {
        if (activePhoto.id == null) {
            return;
        }

        setOptionsById((current) => ({
            ...current,
            [activePhoto.id as number]: { ...(current[activePhoto.id as number] ?? defaultReprocessOptions(activePhoto)), ...patch },
        }));
    };

    const patchCorrection = <K extends CorrectionKey>(key: K, patch: Partial<ReprocessOptions[K]>) => {
        if (activePhoto.id == null) {
            return;
        }

        const id = activePhoto.id;

        setOptionsById((current) => {
            const existing = current[id] ?? defaultReprocessOptions(activePhoto);

            return {
                ...current,
                [id]: { ...existing, [key]: { ...existing[key], ...patch } },
            };
        });
    };

    const setAngle = (value: number) => {
        const rounded = Math.round(value * 100) / 100;

        setActiveAngleText(formatAngle(rounded));
        update({ angle: rounded });
    };

    function setActiveAngleText(text: string) {
        if (activePhoto.id != null) {
            setAngleById((current) => ({ ...current, [activePhoto.id as number]: text }));
        }
    }

    const selectPhoto = (id: number) => {
        setActiveId(id);
        setError(null);
    };

    const toggleCheck = (id: number) => {
        setCheckedIds((current) => {
            const next = new Set(current);

            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
            }

            return next;
        });
    };

    const normalizeSelection = () => {
        if (checkedPhotos.length === 0) {
            setError("Select at least one photo to normalize.");
            return;
        }

        const referenceSource =
            normalizationMode === "reference" && activePhoto.id != null && !checkedPhotos.some((target) => target.id === activePhoto.id)
                ? [activePhoto, ...checkedPhotos]
                : checkedPhotos;
        const next = normalizeReprocessOptions(
            referenceSource,
            normalizationMode,
            activePhoto.id,
            optionsById,
        );

        if (!next) {
            return;
        }

        const ids = checkedPhotos.map((target) => target.id).filter((id): id is number => id != null);

        setOptionsById((current) => {
            const updated = { ...current };

            for (const id of ids) {
                updated[id] = cloneReprocessOptions(next);
            }

            return updated;
        });
        setAngleById((current) => {
            const updated = { ...current };

            for (const id of ids) {
                updated[id] = formatAngle(next.angle);
            }

            return updated;
        });
        setError(null);
    };

    const removeTarget = (size: number) => {
        if (activeOptions.alternatives.length === 1) {
            return;
        }

        const alternatives = activeOptions.alternatives.filter((entry) => entry !== size);

        update({
            alternatives,
            main: alternatives.includes(activeOptions.main) ? activeOptions.main : alternatives[0],
        });
    };

    const addTarget = () => {
        const size = Number.parseInt(newSize, 10);

        if (!Number.isFinite(size) || activeOptions.alternatives.includes(size)) {
            setNewSize("");
            return;
        }

        if (activeOptions.alternatives.length >= MAX_TARGETS) {
            setError(`At most ${MAX_TARGETS} target sizes can be generated.`);
            return;
        }

        setError(null);
        update({ alternatives: [...activeOptions.alternatives, size].sort((a, b) => a - b) });
        setNewSize("");
    };

    const resetActive = () => {
        if (activePhoto.id != null) {
            const id = activePhoto.id;

            setOptionsById((current) => omitIds(current, [id]));
            setAngleById((current) => omitIds(current, [id]));
        }

        setNewSize("");
        setError(null);
    };

    const persist = async (items: SaveItem[]) => {
        setSaving(true);
        setError(null);

        const failed: string[] = [];
        const savedById = new Map<number, Photo>();

        setConfirmOpen(false);

        for (const item of items) {
            if (item.photo.id == null) {
                continue;
            }

            const id = item.photo.id;
            const name = item.photo.filename ?? item.photo.path;

            try {
                const { data, error: requestError } = await api.POST("/api/photos/{photo_id}/reprocess", {
                    params: { path: { photo_id: id } },
                    body: toReprocessPayload(item.options),
                });

                if (requestError || !data) {
                    failed.push(`${name}: ${errorMessage(requestError, "Reprocessing failed.")}`);
                    continue;
                }

                savedById.set(id, data);
            } catch (reason) {
                failed.push(`${name}: ${reason instanceof Error ? reason.message : "Reprocessing failed."}`);
            }
        }

        setSaving(false);

        const savedIds = [...savedById.keys()];

        if (savedIds.length > 0) {
            setOptionsById((current) => omitIds(current, savedIds));
            setAngleById((current) => omitIds(current, savedIds));
            setCheckedIds((current) => {
                const next = new Set(current);

                for (const id of savedIds) {
                    next.delete(id);
                }

                return next;
            });
        }

        if (failed.length > 0) {
            setError(failed.join(" · "));
            return;
        }

        onUpdated(photo.id != null ? (savedById.get(photo.id) ?? photo) : photo);
        onClose();
    };

    const requestSave = () => {
        if (activePhoto.id == null) {
            return;
        }

        const items: SaveItem[] = savePhotos
            .filter((target) => target.id != null)
            .map((target) => ({ photo: target, options: optionsFor(target) }));

        if (items.length === 0) {
            setError("Select at least one photo to reprocess.");
            return;
        }

        const invalid = items
            .map((item) => ({ item, problem: validateOptions(item.options) }))
            .find((entry) => entry.problem !== null);

        if (invalid?.problem) {
            setActiveId(invalid.item.photo.id ?? null);
            setError(`${invalid.item.photo.filename ?? invalid.item.photo.path}: ${invalid.problem}`);
            return;
        }

        setError(null);

        if (multiEdit) {
            setPendingSave(items);
            setConfirmOpen(true);
            return;
        }

        void persist(items);
    };

    return (
        <Dialog
            open
            fullScreen
            onClose={saving ? undefined : onClose}
            slotProps={{ paper: { sx: { bgcolor: "background.default" } } }}
        >
            <Box sx={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
                <Box
                    sx={{
                        display: "flex",
                        alignItems: "center",
                        gap: 1,
                        px: 2,
                        py: 1,
                        borderBottom: 1,
                        borderColor: "divider",
                    }}
                >
                    <Box sx={{ minWidth: 0 }}>
                        <Typography variant="h6" sx={{ lineHeight: 1.2 }}>
                            Adjust processing
                        </Typography>
                        <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
                            {activePhoto.filename ?? activePhoto.path}
                            {multiEdit && ` · ${checkedPhotos.length} selected`}
                        </Typography>
                    </Box>
                    {multiEdit && <Chip size="small" color="primary" label="Multi-edit" />}
                    <Box sx={{ flex: 1 }} />
                    <Button startIcon={<RestartAltIcon />} onClick={resetActive} disabled={saving}>
                        Reset
                    </Button>
                    <Button onClick={onClose} disabled={saving}>
                        Cancel
                    </Button>
                    <Button
                        variant="contained"
                        onClick={requestSave}
                        disabled={saving || savePhotos.length === 0}
                        startIcon={saving ? <CircularProgress size={16} color="inherit" /> : undefined}
                    >
                        {multiEdit ? `Save ${savePhotos.length} photos` : "Reprocess"}
                    </Button>
                </Box>

                <Box sx={{ flex: 1, minHeight: 0, display: "flex" }}>
                    <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
                        <Box sx={{ flex: 1, minHeight: 0 }}>
                            <ProcessingPreview
                                imageUrl={activePreview?.url ?? null}
                                model={model}
                                corrections={corrections}
                                loading={!activePreview && !activePreviewError}
                                error={activePreviewError?.message ?? null}
                            />
                        </Box>
                        <Box
                            sx={{
                                display: "flex",
                                flexWrap: "wrap",
                                alignItems: "center",
                                gap: 2,
                                px: 2,
                                py: 1,
                                borderTop: 1,
                                borderColor: "divider",
                            }}
                        >
                            <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
                                <Box sx={{ width: 18, height: 2, bgcolor: "#ff5252" }} />
                                <Typography variant="caption" color="text.secondary">
                                    Detected horizon
                                </Typography>
                            </Box>
                            <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
                                <Box sx={{ width: 18, borderTop: "2px dashed #00e676" }} />
                                <Typography variant="caption" color="text.secondary">
                                    Level target
                                </Typography>
                            </Box>
                            <Box sx={{ flex: 1 }} />
                            {activePreview && (
                                <Typography variant="caption" color="text.secondary">
                                    Source {activePreview.width} × {activePreview.height} px
                                </Typography>
                            )}
                            {model && (
                                <>
                                    <Typography variant="caption" color="text.secondary">
                                        Crop {model.cropSize.width} × {model.cropSize.height} px
                                    </Typography>
                                    <Typography variant="caption">
                                        Output {model.output.width} × {model.output.height} px
                                    </Typography>
                                </>
                            )}
                        </Box>
                    </Box>

                    <Box
                        sx={{
                            width: SIDE_PANEL_WIDTH,
                            flexShrink: 0,
                            borderLeft: 1,
                            borderColor: "divider",
                            display: "flex",
                            flexDirection: "column",
                            minHeight: 0,
                        }}
                    >
                        <Accordion
                            defaultExpanded
                            disableGutters
                            elevation={0}
                            sx={{ flexShrink: 0, borderRadius: 0, borderBottom: 1, borderColor: "divider" }}
                        >
                            <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 40 }}>
                                <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, width: "100%" }}>
                                    <PhotoLibraryIcon fontSize="small" />
                                    <Typography variant="subtitle2">Nearby photos</Typography>
                                    <Box sx={{ flex: 1 }} />
                                    <Typography variant="caption" color="text.secondary">
                                        {galleryPhotos.length}
                                    </Typography>
                                </Box>
                            </AccordionSummary>
                            <AccordionDetails sx={{ display: "flex", flexDirection: "column", gap: 1, pt: 0 }}>
                                <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1, alignItems: "center" }}>
                                    <TextField
                                        size="small"
                                        label="Time window"
                                        value={windowText}
                                        onChange={(event) => setWindowText(event.target.value)}
                                        onBlur={() => {
                                            const parsed = parseWindow(windowText);

                                            if (parsed) {
                                                setWindowText(formatWindow(parsed.value, parsed.unit));
                                            } else {
                                                setError("Enter a time window like “30 min”.");
                                            }
                                        }}
                                        sx={{ width: 116 }}
                                    />
                                    {multiEdit && (
                                        <TextField
                                            select
                                            size="small"
                                            label="Normalization"
                                            value={normalizationMode}
                                            onChange={(event) => setNormalizationMode(event.target.value as NormalizationMode)}
                                            sx={{ minWidth: 120 }}
                                        >
                                            <MenuItem value="reference">Reference</MenuItem>
                                            <MenuItem value="barycentric">Barycentric</MenuItem>
                                        </TextField>
                                    )}
                                    <Button
                                        size="small"
                                        onClick={() => void loadCandidates()}
                                        disabled={finding || photo.id == null || parseWindow(windowText) === null}
                                        startIcon={finding ? <CircularProgress size={14} color="inherit" /> : undefined}
                                    >
                                        Auto-detect
                                    </Button>
                                    <Button
                                        size="small"
                                        onClick={() => setCheckedIds(new Set(candidateIds))}
                                        disabled={candidateIds.length === 0}
                                    >
                                        Select all
                                    </Button>
                                    <Button size="small" onClick={() => setCheckedIds(new Set())} disabled={checkedIds.size === 0}>
                                        Clear
                                    </Button>
                                    {multiEdit && (
                                        <Button size="small" onClick={normalizeSelection} disabled={checkedPhotos.length === 0}>
                                            Normalize
                                        </Button>
                                    )}
                                </Box>
                                {candidateError && <Alert severity="error">{candidateError}</Alert>}
                                {error && <Alert severity="error">{error}</Alert>}
                                <Box sx={{ height: 220, overflowY: "auto" }}>
                                    <ThumbnailGallery
                                        photoIds={candidateIds}
                                        selectedPhotoId={activePhoto.id ?? null}
                                        referenceId={activePhoto.id ?? null}
                                        checkedIds={checkedIds}
                                        onToggleCheck={toggleCheck}
                                        badges={badges}
                                        editedIds={editedIds}
                                        thumbSize={96}
                                        onSelect={selectPhoto}
                                    />
                                </Box>
                            </AccordionDetails>
                        </Accordion>
                        <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
                            <CorrectionAccordion
                                title="Exposure"
                                enabled={activeOptions.exposure.enabled}
                                onEnabled={(enabled) => patchCorrection("exposure", { enabled })}
                            >
                                <SliderRow
                                    label="Exposure"
                                    value={activeOptions.exposure.exposure}
                                    min={-6}
                                    max={6}
                                    step={0.05}
                                    format={(value) => `${value > 0 ? "+" : ""}${value.toFixed(2)} EV`}
                                    onChange={(exposure) => patchCorrection("exposure", { exposure })}
                                />
                                <SliderRow
                                    label="Gamma"
                                    value={activeOptions.exposure.gamma}
                                    min={0.2}
                                    max={5}
                                    step={0.05}
                                    format={(value) => value.toFixed(2)}
                                    onChange={(gamma) => patchCorrection("exposure", { gamma })}
                                />
                            </CorrectionAccordion>

                            <CorrectionAccordion
                                title="White balance"
                                enabled={activeOptions.whiteBalance.enabled}
                                onEnabled={(enabled) => patchCorrection("whiteBalance", { enabled })}
                            >
                                <TextField
                                    select
                                    size="small"
                                    label="Method"
                                    value={activeOptions.whiteBalance.method}
                                    onChange={(event) =>
                                        patchCorrection("whiteBalance", {
                                            method: event.target.value as "gray_world" | "manual",
                                        })
                                    }
                                >
                                    <MenuItem value="gray_world">Gray World</MenuItem>
                                    <MenuItem value="manual">Manual</MenuItem>
                                </TextField>
                                <SliderRow
                                    label="Strength"
                                    value={activeOptions.whiteBalance.strength}
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    format={(value) => `${Math.round(value * 100)}%`}
                                    onChange={(strength) => patchCorrection("whiteBalance", { strength })}
                                />
                                {activeOptions.whiteBalance.method === "manual" && (
                                    <>
                                        <SliderRow
                                            label="Temperature"
                                            value={activeOptions.whiteBalance.temperature}
                                            min={-1}
                                            max={1}
                                            step={0.01}
                                            format={(value) => value.toFixed(2)}
                                            onChange={(temperature) => patchCorrection("whiteBalance", { temperature })}
                                        />
                                        <SliderRow
                                            label="Tint"
                                            value={activeOptions.whiteBalance.tint}
                                            min={-1}
                                            max={1}
                                            step={0.01}
                                            format={(value) => value.toFixed(2)}
                                            onChange={(tint) => patchCorrection("whiteBalance", { tint })}
                                        />
                                    </>
                                )}
                            </CorrectionAccordion>

                            <CorrectionAccordion
                                title="Contrast"
                                enabled={activeOptions.contrast.enabled}
                                onEnabled={(enabled) => patchCorrection("contrast", { enabled })}
                            >
                                <TextField
                                    select
                                    size="small"
                                    label="Method"
                                    value={activeOptions.contrast.method}
                                    onChange={(event) =>
                                        patchCorrection("contrast", {
                                            method: event.target.value as "s_curve" | "adaptive",
                                        })
                                    }
                                >
                                    <MenuItem value="s_curve">S-curve</MenuItem>
                                    <MenuItem value="adaptive">Adaptive</MenuItem>
                                </TextField>
                                <SliderRow
                                    label="Strength"
                                    value={activeOptions.contrast.strength}
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    format={(value) => `${Math.round(value * 100)}%`}
                                    onChange={(strength) => patchCorrection("contrast", { strength })}
                                />
                                {activeOptions.contrast.method === "adaptive" && (
                                    <>
                                        <SliderRow
                                            label="Black point percentile"
                                            value={activeOptions.contrast.low_percentile}
                                            min={0}
                                            max={100}
                                            step={1}
                                            onChange={(low_percentile) => patchCorrection("contrast", { low_percentile })}
                                        />
                                        <SliderRow
                                            label="White point percentile"
                                            value={activeOptions.contrast.high_percentile}
                                            min={0}
                                            max={100}
                                            step={1}
                                            onChange={(high_percentile) =>
                                                patchCorrection("contrast", { high_percentile })
                                            }
                                        />
                                    </>
                                )}
                            </CorrectionAccordion>

                            <CorrectionAccordion
                                title="Local contrast"
                                enabled={activeOptions.localContrast.enabled}
                                onEnabled={(enabled) => patchCorrection("localContrast", { enabled })}
                            >
                                <SliderRow
                                    label="Clip limit"
                                    value={activeOptions.localContrast.clip_limit}
                                    min={0.01}
                                    max={20}
                                    step={0.1}
                                    format={(value) => value.toFixed(2)}
                                    onChange={(clip_limit) => patchCorrection("localContrast", { clip_limit })}
                                />
                                <SliderRow
                                    label="Tile grid"
                                    value={activeOptions.localContrast.tile_grid}
                                    min={1}
                                    max={64}
                                    step={1}
                                    onChange={(tile_grid) => patchCorrection("localContrast", { tile_grid })}
                                />
                                <SliderRow
                                    label="Strength"
                                    value={activeOptions.localContrast.strength}
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    format={(value) => `${Math.round(value * 100)}%`}
                                    onChange={(strength) => patchCorrection("localContrast", { strength })}
                                />
                            </CorrectionAccordion>

                            <CorrectionAccordion
                                title="Vibrance"
                                enabled={activeOptions.vibrance.enabled}
                                onEnabled={(enabled) => patchCorrection("vibrance", { enabled })}
                            >
                                <SliderRow
                                    label="Strength"
                                    value={activeOptions.vibrance.strength}
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    format={(value) => `${Math.round(value * 100)}%`}
                                    onChange={(strength) => patchCorrection("vibrance", { strength })}
                                />
                            </CorrectionAccordion>

                            <Accordion disableGutters defaultExpanded>
                                <AccordionSummary
                                    expandIcon={<ExpandMoreIcon />}
                                    sx={{ fontWeight: 600, fontSize: 14, minHeight: 40 }}
                                >
                                    Tilt
                                </AccordionSummary>
                                <AccordionDetails sx={{ display: "flex", flexDirection: "column", gap: 1.5 }}>
                                    <RadioGroup
                                        row
                                        value={activeOptions.tiltMode}
                                        onChange={(event) => update({ tiltMode: event.target.value as TiltMode })}
                                    >
                                        <FormControlLabel value="auto" control={<Radio size="small" />} label="Auto" />
                                        <FormControlLabel value="off" control={<Radio size="small" />} label="Off" />
                                        <FormControlLabel
                                            value="manual"
                                            control={<Radio size="small" />}
                                            label="Manual"
                                        />
                                    </RadioGroup>

                                    {activeOptions.tiltMode === "manual" ? (
                                        <Box sx={{ display: "flex", flexDirection: "column", gap: 0.5 }}>
                                            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                                                <Slider
                                                    min={-MAX_MANUAL_ANGLE}
                                                    max={MAX_MANUAL_ANGLE}
                                                    step={0.1}
                                                    value={activeOptions.angle}
                                                    onChange={(_, value) => setAngle(value as number)}
                                                    sx={{ flex: 1 }}
                                                />
                                                <TextField
                                                    size="small"
                                                    type="number"
                                                    value={angleText}
                                                    onChange={(event) => {
                                                        const text = event.target.value;
                                                        setActiveAngleText(text);
                                                        const parsed = Number(text);

                                                        if (text !== "" && Number.isFinite(parsed)) {
                                                            update({ angle: parsed });
                                                        }
                                                    }}
                                                    onBlur={() => setActiveAngleText(formatAngle(activeOptions.angle))}
                                                    slotProps={{
                                                        htmlInput: {
                                                            step: 0.1,
                                                            min: -MAX_MANUAL_ANGLE,
                                                            max: MAX_MANUAL_ANGLE,
                                                        },
                                                    }}
                                                    sx={{ width: 92 }}
                                                />
                                            </Box>
                                            <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                                <Typography variant="caption" color="text.secondary">
                                                    Degrees, ±{MAX_MANUAL_ANGLE}
                                                </Typography>
                                                {tilt.detectedAngle !== null && (
                                                    <Button
                                                        size="small"
                                                        onClick={() => {
                                                            update({ tiltMode: "manual" });
                                                            setAngle(tilt.detectedAngle as number);
                                                        }}
                                                    >
                                                        Use detected
                                                    </Button>
                                                )}
                                            </Box>
                                        </Box>
                                    ) : (
                                        <Typography variant="caption" color="text.secondary">
                                            {activeOptions.tiltMode === "off"
                                                ? "The photo is not rotated."
                                                : correction === 0
                                                  ? "No correction is applied."
                                                  : `Corrects the horizon by ${correction.toFixed(2)}°.`}
                                        </Typography>
                                    )}

                                    {tilt.step && <DetailRows details={tilt.step.details} />}
                                </AccordionDetails>
                            </Accordion>

                            <Accordion disableGutters defaultExpanded>
                                <AccordionSummary
                                    expandIcon={<ExpandMoreIcon />}
                                    sx={{ fontWeight: 600, fontSize: 14, minHeight: 40 }}
                                >
                                    Crop
                                </AccordionSummary>
                                <AccordionDetails sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
                                    <TextField
                                        select
                                        size="small"
                                        label="Crop mode"
                                        value={activeOptions.cropMode}
                                        onChange={(event) => update({ cropMode: event.target.value as CropMode })}
                                    >
                                        <MenuItem value="maximum_valid_rectangle">Maximum valid rectangle</MenuItem>
                                        <MenuItem value="none">Keep expanded canvas</MenuItem>
                                    </TextField>
                                    <Typography variant="caption" color="text.secondary">
                                        {activeOptions.cropMode === "none"
                                            ? "Keeps the rotated canvas, including the empty corners."
                                            : "Trims the borders the rotation introduces."}
                                    </Typography>
                                    {model && (
                                        <SizeRow
                                            label="Remaining"
                                            width={model.cropSize.width}
                                            height={model.cropSize.height}
                                        />
                                    )}
                                </AccordionDetails>
                            </Accordion>

                            <Accordion disableGutters defaultExpanded>
                                <AccordionSummary
                                    expandIcon={<ExpandMoreIcon />}
                                    sx={{ fontWeight: 600, fontSize: 14, minHeight: 40 }}
                                >
                                    Rescale
                                </AccordionSummary>
                                <AccordionDetails sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
                                    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                                        {activeOptions.alternatives.map((size) => (
                                            <Chip
                                                key={size}
                                                size="small"
                                                label={size}
                                                color={size === activeOptions.main ? "primary" : "default"}
                                                onDelete={
                                                    activeOptions.alternatives.length > 1
                                                        ? () => removeTarget(size)
                                                        : undefined
                                                }
                                            />
                                        ))}
                                    </Box>
                                    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                                        <TextField
                                            size="small"
                                            type="number"
                                            label="Add size"
                                            value={newSize}
                                            onChange={(event) => setNewSize(event.target.value)}
                                            onKeyDown={(event) => {
                                                if (event.key === "Enter") {
                                                    event.preventDefault();
                                                    addTarget();
                                                }
                                            }}
                                            slotProps={{
                                                htmlInput: {
                                                    min: MIN_TARGET_SIZE,
                                                    max: MAX_TARGET_SIZE,
                                                    step: 1,
                                                },
                                            }}
                                            sx={{ flex: 1 }}
                                        />
                                        <Button size="small" onClick={addTarget} disabled={newSize === ""}>
                                            Add
                                        </Button>
                                    </Box>
                                    <TextField
                                        select
                                        size="small"
                                        label="Main size"
                                        value={activeOptions.main}
                                        onChange={(event) => update({ main: Number(event.target.value) })}
                                    >
                                        {activeOptions.alternatives.map((size) => (
                                            <MenuItem key={size} value={size}>
                                                {size} px
                                            </MenuItem>
                                        ))}
                                    </TextField>
                                    <Typography variant="caption" color="text.secondary">
                                        Longest edge in pixels ({MIN_TARGET_SIZE}–{MAX_TARGET_SIZE}). The main size is what
                                        the gallery and the scanners use.
                                    </Typography>
                                    {model && <SizeRow label="Output" width={model.output.width} height={model.output.height} />}
                                </AccordionDetails>
                            </Accordion>

                            <CorrectionAccordion
                                title="Noise reduction"
                                enabled={activeOptions.noiseReduction.enabled}
                                onEnabled={(enabled) => patchCorrection("noiseReduction", { enabled })}
                            >
                                <TextField
                                    select
                                    size="small"
                                    label="Method"
                                    value={activeOptions.noiseReduction.method}
                                    onChange={(event) =>
                                        patchCorrection("noiseReduction", {
                                            method: event.target.value as "bilateral" | "nl_means",
                                        })
                                    }
                                >
                                    <MenuItem value="bilateral">Bilateral</MenuItem>
                                    <MenuItem value="nl_means">Non-local means</MenuItem>
                                </TextField>
                                {activeOptions.noiseReduction.method === "bilateral" ? (
                                    <>
                                        <SliderRow
                                            label="Radius"
                                            value={activeOptions.noiseReduction.radius}
                                            min={1}
                                            max={30}
                                            step={1}
                                            onChange={(radius) => patchCorrection("noiseReduction", { radius })}
                                        />
                                        <SliderRow
                                            label="Colour sigma"
                                            value={activeOptions.noiseReduction.sigma_color}
                                            min={1}
                                            max={200}
                                            step={1}
                                            onChange={(sigma_color) => patchCorrection("noiseReduction", { sigma_color })}
                                        />
                                        <SliderRow
                                            label="Spatial sigma"
                                            value={activeOptions.noiseReduction.sigma_space}
                                            min={1}
                                            max={200}
                                            step={1}
                                            onChange={(sigma_space) => patchCorrection("noiseReduction", { sigma_space })}
                                        />
                                    </>
                                ) : (
                                    <SliderRow
                                        label="Strength"
                                        value={activeOptions.noiseReduction.strength}
                                        min={1}
                                        max={30}
                                        step={1}
                                        onChange={(strength) => patchCorrection("noiseReduction", { strength })}
                                    />
                                )}
                                <Typography variant="caption" color="text.secondary">
                                    Preview uses a fast blur approximation; the saved file uses the selected algorithm.
                                </Typography>
                            </CorrectionAccordion>

                            <CorrectionAccordion
                                title="Sharpening"
                                enabled={activeOptions.sharpening.enabled}
                                onEnabled={(enabled) => patchCorrection("sharpening", { enabled })}
                            >
                                <SliderRow
                                    label="Radius"
                                    value={activeOptions.sharpening.radius}
                                    min={0.1}
                                    max={10}
                                    step={0.1}
                                    format={(value) => value.toFixed(1)}
                                    onChange={(radius) => patchCorrection("sharpening", { radius })}
                                />
                                <SliderRow
                                    label="Amount"
                                    value={activeOptions.sharpening.amount}
                                    min={0}
                                    max={3}
                                    step={0.05}
                                    format={(value) => value.toFixed(2)}
                                    onChange={(amount) => patchCorrection("sharpening", { amount })}
                                />
                                <SliderRow
                                    label="Threshold"
                                    value={activeOptions.sharpening.threshold}
                                    min={0}
                                    max={50}
                                    step={1}
                                    onChange={(threshold) => patchCorrection("sharpening", { threshold })}
                                />
                            </CorrectionAccordion>

                            <Accordion disableGutters>
                                <AccordionSummary
                                    expandIcon={<ExpandMoreIcon />}
                                    sx={{ fontWeight: 600, fontSize: 14, minHeight: 40 }}
                                >
                                    Analysis
                                </AccordionSummary>
                                <AccordionDetails>
                                    <FormControlLabel
                                        control={
                                            <Switch
                                                checked={activeOptions.rescan}
                                                onChange={(event) => update({ rescan: event.target.checked })}
                                            />
                                        }
                                        label="Re-run analysis"
                                    />
                                    <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                                        Recomputes object and duplicate detection on the new main image. EXIF, tags,
                                        location and dates are kept.
                                    </Typography>
                                </AccordionDetails>
                            </Accordion>

                        </Box>
                    </Box>
                </Box>
            </Box>

            <Dialog
                open={confirmOpen}
                onClose={saving ? undefined : () => setConfirmOpen(false)}
                maxWidth="sm"
                fullWidth
            >
                <Box sx={{ p: 3 }}>
                    <Typography variant="h6">Save changes to {pendingSave.length} photos?</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                        Each photo keeps its own parameters. They will be re-encoded one after another.
                    </Typography>
                    <Box
                        sx={{
                            mt: 2,
                            maxHeight: 220,
                            overflowY: "auto",
                            border: 1,
                            borderColor: "divider",
                            borderRadius: 1,
                        }}
                    >
                        {pendingSave.map((item) => (
                            <Box
                                key={item.photo.id}
                                sx={{ px: 1.5, py: 0.75, borderBottom: 1, borderColor: "divider" }}
                            >
                                <Typography variant="body2" noWrap>
                                    {item.photo.filename ?? item.photo.path}
                                </Typography>
                            </Box>
                        ))}
                    </Box>
                    <Box sx={{ display: "flex", justifyContent: "flex-end", gap: 1, mt: 3 }}>
                        <Button onClick={() => setConfirmOpen(false)} disabled={saving}>
                            Cancel
                        </Button>
                        <Button
                            variant="contained"
                            onClick={() => void persist(pendingSave)}
                            disabled={saving || pendingSave.length === 0}
                            startIcon={saving ? <CircularProgress size={16} color="inherit" /> : undefined}
                        >
                            Save {pendingSave.length}
                        </Button>
                    </Box>
                </Box>
            </Dialog>
        </Dialog>
    );
}
