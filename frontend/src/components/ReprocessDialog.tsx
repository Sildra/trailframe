import { useEffect, useMemo, useState, type ReactNode } from "react";
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
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import { SIDE_PANEL_WIDTH } from "../lib/layout";
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

type Photo = components["schemas"]["PhotoDetail"];

interface ReprocessDialogProps {
    photo: Photo;
    onClose: () => void;
    onUpdated: (photo: Photo) => void;
}

interface PreviewImage {
    url: string;
    width: number;
    height: number;
}

function formatAngle(value: number): string {
    return String(Math.round(value * 100) / 100);
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
    const [options, setOptions] = useState<ReprocessOptions>(() => defaultReprocessOptions(photo));
    const [angleText, setAngleText] = useState(() => formatAngle(defaultReprocessOptions(photo).angle));
    const [newSize, setNewSize] = useState("");
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [preview, setPreview] = useState<PreviewImage | null>(null);
    const [previewError, setPreviewError] = useState<string | null>(null);

    const corrections = useMemo<PreviewCorrections>(
        () => ({
            exposure: options.exposure,
            whiteBalance: options.whiteBalance,
            contrast: options.contrast,
            localContrast: options.localContrast,
            vibrance: options.vibrance,
            noiseReduction: options.noiseReduction,
            sharpening: options.sharpening,
        }),
        [
            options.exposure,
            options.whiteBalance,
            options.contrast,
            options.localContrast,
            options.vibrance,
            options.noiseReduction,
            options.sharpening,
        ],
    );

    const tilt = useMemo(() => {
        const step = normalizeProcessing(photo.processing).find((entry) => entry.step === "tilt") ?? null;

        return {
            step,
            line: step ? parseLine(step.meta.line) : null,
            reference: step ? parsePoint(step.meta.reference_point) : null,
            detectedAngle: step ? parseAngle(step.summary) : null,
            applied: step?.meta.applied === true,
        };
    }, [photo.processing]);

    useEffect(() => {
        if (photo.id == null) {
            return;
        }

        const controller = new AbortController();
        let objectUrl: string | null = null;

        fetch(`./api/photos/${photo.id}/preview?size=1200`, { signal: controller.signal })
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
                setPreview({ url: objectUrl, width, height });
            })
            .catch((reason: unknown) => {
                if (!controller.signal.aborted) {
                    setPreviewError(reason instanceof Error ? reason.message : "Preview unavailable.");
                }
            });

        return () => {
            controller.abort();

            if (objectUrl) {
                URL.revokeObjectURL(objectUrl);
            }
        };
    }, [photo.id]);

    const correction = effectiveAngle(options.tiltMode, options.angle, tilt.detectedAngle, tilt.applied);
    const model = useMemo(() => {
        if (!preview) {
            return null;
        }

        return buildPreview(
            { width: preview.width, height: preview.height },
            { line: tilt.line, reference: tilt.reference, detectedAngle: tilt.detectedAngle },
            { angle: correction, cropMode: options.cropMode, target: options.main },
        );
    }, [preview, tilt, correction, options.cropMode, options.main]);

    const update = (patch: Partial<ReprocessOptions>) =>
        setOptions((current) => ({ ...current, ...patch }));

    const patchCorrection = <K extends CorrectionKey>(key: K, patch: Partial<ReprocessOptions[K]>) =>
        setOptions((current) => ({ ...current, [key]: { ...current[key], ...patch } }));

    const setAngle = (value: number) => {
        const rounded = Math.round(value * 100) / 100;
        setAngleText(formatAngle(rounded));
        update({ angle: rounded });
    };

    const removeTarget = (size: number) => {
        setOptions((current) => {
            if (current.alternatives.length === 1) {
                return current;
            }

            const alternatives = current.alternatives.filter((entry) => entry !== size);

            return {
                ...current,
                alternatives,
                main: alternatives.includes(current.main) ? current.main : alternatives[0],
            };
        });
    };

    const addTarget = () => {
        const size = Number.parseInt(newSize, 10);

        if (!Number.isFinite(size) || options.alternatives.includes(size)) {
            setNewSize("");
            return;
        }

        if (options.alternatives.length >= MAX_TARGETS) {
            setError(`At most ${MAX_TARGETS} target sizes can be generated.`);
            return;
        }

        setError(null);
        update({ alternatives: [...options.alternatives, size].sort((a, b) => a - b) });
        setNewSize("");
    };

    const reset = () => {
        const next = defaultReprocessOptions(photo);
        setOptions(next);
        setAngleText(formatAngle(next.angle));
        setNewSize("");
        setError(null);
    };

    const save = async () => {
        const invalid = validateOptions(options);

        if (invalid) {
            setError(invalid);
            return;
        }

        if (photo.id == null) {
            return;
        }

        setSaving(true);
        setError(null);

        const { data, error: requestError } = await api.POST("/api/photos/{photo_id}/reprocess", {
            params: { path: { photo_id: photo.id } },
            body: toReprocessPayload(options),
        });

        setSaving(false);

        if (requestError || !data) {
            const detail = (requestError as { detail?: unknown } | undefined)?.detail;
            setError(typeof detail === "string" ? detail : "Reprocessing failed.");
            return;
        }

        onUpdated(data);
        onClose();
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
                            {photo.filename ?? photo.path}
                        </Typography>
                    </Box>
                    <Box sx={{ flex: 1 }} />
                    <Button startIcon={<RestartAltIcon />} onClick={reset} disabled={saving}>
                        Reset
                    </Button>
                    <Button onClick={onClose} disabled={saving}>
                        Cancel
                    </Button>
                    <Button
                        variant="contained"
                        onClick={save}
                        disabled={saving || photo.id == null}
                        startIcon={saving ? <CircularProgress size={16} color="inherit" /> : undefined}
                    >
                        Reprocess
                    </Button>
                </Box>

                <Box sx={{ flex: 1, minHeight: 0, display: "flex" }}>
                    <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
                        <Box sx={{ flex: 1, minHeight: 0 }}>
                            <ProcessingPreview
                                imageUrl={preview?.url ?? null}
                                model={model}
                                corrections={corrections}
                                loading={!preview && !previewError}
                                error={previewError}
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
                            {preview && (
                                <Typography variant="caption" color="text.secondary">
                                    Source {preview.width} × {preview.height} px
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
                        <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
                            <CorrectionAccordion
                                title="Exposure"
                                enabled={options.exposure.enabled}
                                onEnabled={(enabled) => patchCorrection("exposure", { enabled })}
                            >
                                <SliderRow
                                    label="Exposure"
                                    value={options.exposure.exposure}
                                    min={-6}
                                    max={6}
                                    step={0.05}
                                    format={(value) => `${value > 0 ? "+" : ""}${value.toFixed(2)} EV`}
                                    onChange={(exposure) => patchCorrection("exposure", { exposure })}
                                />
                                <SliderRow
                                    label="Gamma"
                                    value={options.exposure.gamma}
                                    min={0.2}
                                    max={5}
                                    step={0.05}
                                    format={(value) => value.toFixed(2)}
                                    onChange={(gamma) => patchCorrection("exposure", { gamma })}
                                />
                            </CorrectionAccordion>

                            <CorrectionAccordion
                                title="White balance"
                                enabled={options.whiteBalance.enabled}
                                onEnabled={(enabled) => patchCorrection("whiteBalance", { enabled })}
                            >
                                <TextField
                                    select
                                    size="small"
                                    label="Method"
                                    value={options.whiteBalance.method}
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
                                    value={options.whiteBalance.strength}
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    format={(value) => `${Math.round(value * 100)}%`}
                                    onChange={(strength) => patchCorrection("whiteBalance", { strength })}
                                />
                                {options.whiteBalance.method === "manual" && (
                                    <>
                                        <SliderRow
                                            label="Temperature"
                                            value={options.whiteBalance.temperature}
                                            min={-1}
                                            max={1}
                                            step={0.01}
                                            format={(value) => value.toFixed(2)}
                                            onChange={(temperature) => patchCorrection("whiteBalance", { temperature })}
                                        />
                                        <SliderRow
                                            label="Tint"
                                            value={options.whiteBalance.tint}
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
                                enabled={options.contrast.enabled}
                                onEnabled={(enabled) => patchCorrection("contrast", { enabled })}
                            >
                                <TextField
                                    select
                                    size="small"
                                    label="Method"
                                    value={options.contrast.method}
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
                                    value={options.contrast.strength}
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    format={(value) => `${Math.round(value * 100)}%`}
                                    onChange={(strength) => patchCorrection("contrast", { strength })}
                                />
                                {options.contrast.method === "adaptive" && (
                                    <>
                                        <SliderRow
                                            label="Black point percentile"
                                            value={options.contrast.low_percentile}
                                            min={0}
                                            max={100}
                                            step={1}
                                            onChange={(low_percentile) => patchCorrection("contrast", { low_percentile })}
                                        />
                                        <SliderRow
                                            label="White point percentile"
                                            value={options.contrast.high_percentile}
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
                                enabled={options.localContrast.enabled}
                                onEnabled={(enabled) => patchCorrection("localContrast", { enabled })}
                            >
                                <SliderRow
                                    label="Clip limit"
                                    value={options.localContrast.clip_limit}
                                    min={0.01}
                                    max={20}
                                    step={0.1}
                                    format={(value) => value.toFixed(2)}
                                    onChange={(clip_limit) => patchCorrection("localContrast", { clip_limit })}
                                />
                                <SliderRow
                                    label="Tile grid"
                                    value={options.localContrast.tile_grid}
                                    min={1}
                                    max={64}
                                    step={1}
                                    onChange={(tile_grid) => patchCorrection("localContrast", { tile_grid })}
                                />
                                <SliderRow
                                    label="Strength"
                                    value={options.localContrast.strength}
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    format={(value) => `${Math.round(value * 100)}%`}
                                    onChange={(strength) => patchCorrection("localContrast", { strength })}
                                />
                            </CorrectionAccordion>

                            <CorrectionAccordion
                                title="Vibrance"
                                enabled={options.vibrance.enabled}
                                onEnabled={(enabled) => patchCorrection("vibrance", { enabled })}
                            >
                                <SliderRow
                                    label="Strength"
                                    value={options.vibrance.strength}
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
                                        value={options.tiltMode}
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

                                    {options.tiltMode === "manual" ? (
                                        <Box sx={{ display: "flex", flexDirection: "column", gap: 0.5 }}>
                                            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                                                <Slider
                                                    min={-MAX_MANUAL_ANGLE}
                                                    max={MAX_MANUAL_ANGLE}
                                                    step={0.1}
                                                    value={options.angle}
                                                    onChange={(_, value) => setAngle(value as number)}
                                                    sx={{ flex: 1 }}
                                                />
                                                <TextField
                                                    size="small"
                                                    type="number"
                                                    value={angleText}
                                                    onChange={(event) => {
                                                        const text = event.target.value;
                                                        setAngleText(text);
                                                        const parsed = Number(text);

                                                        if (text !== "" && Number.isFinite(parsed)) {
                                                            update({ angle: parsed });
                                                        }
                                                    }}
                                                    onBlur={() => setAngleText(formatAngle(options.angle))}
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
                                            {options.tiltMode === "off"
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
                                        value={options.cropMode}
                                        onChange={(event) => update({ cropMode: event.target.value as CropMode })}
                                    >
                                        <MenuItem value="maximum_valid_rectangle">Maximum valid rectangle</MenuItem>
                                        <MenuItem value="none">Keep expanded canvas</MenuItem>
                                    </TextField>
                                    <Typography variant="caption" color="text.secondary">
                                        {options.cropMode === "none"
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
                                        {options.alternatives.map((size) => (
                                            <Chip
                                                key={size}
                                                size="small"
                                                label={size}
                                                color={size === options.main ? "primary" : "default"}
                                                onDelete={
                                                    options.alternatives.length > 1
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
                                        value={options.main}
                                        onChange={(event) => update({ main: Number(event.target.value) })}
                                    >
                                        {options.alternatives.map((size) => (
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
                                enabled={options.noiseReduction.enabled}
                                onEnabled={(enabled) => patchCorrection("noiseReduction", { enabled })}
                            >
                                <TextField
                                    select
                                    size="small"
                                    label="Method"
                                    value={options.noiseReduction.method}
                                    onChange={(event) =>
                                        patchCorrection("noiseReduction", {
                                            method: event.target.value as "bilateral" | "nl_means",
                                        })
                                    }
                                >
                                    <MenuItem value="bilateral">Bilateral</MenuItem>
                                    <MenuItem value="nl_means">Non-local means</MenuItem>
                                </TextField>
                                {options.noiseReduction.method === "bilateral" ? (
                                    <>
                                        <SliderRow
                                            label="Radius"
                                            value={options.noiseReduction.radius}
                                            min={1}
                                            max={30}
                                            step={1}
                                            onChange={(radius) => patchCorrection("noiseReduction", { radius })}
                                        />
                                        <SliderRow
                                            label="Colour sigma"
                                            value={options.noiseReduction.sigma_color}
                                            min={1}
                                            max={200}
                                            step={1}
                                            onChange={(sigma_color) => patchCorrection("noiseReduction", { sigma_color })}
                                        />
                                        <SliderRow
                                            label="Spatial sigma"
                                            value={options.noiseReduction.sigma_space}
                                            min={1}
                                            max={200}
                                            step={1}
                                            onChange={(sigma_space) => patchCorrection("noiseReduction", { sigma_space })}
                                        />
                                    </>
                                ) : (
                                    <SliderRow
                                        label="Strength"
                                        value={options.noiseReduction.strength}
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
                                enabled={options.sharpening.enabled}
                                onEnabled={(enabled) => patchCorrection("sharpening", { enabled })}
                            >
                                <SliderRow
                                    label="Radius"
                                    value={options.sharpening.radius}
                                    min={0.1}
                                    max={10}
                                    step={0.1}
                                    format={(value) => value.toFixed(1)}
                                    onChange={(radius) => patchCorrection("sharpening", { radius })}
                                />
                                <SliderRow
                                    label="Amount"
                                    value={options.sharpening.amount}
                                    min={0}
                                    max={3}
                                    step={0.05}
                                    format={(value) => value.toFixed(2)}
                                    onChange={(amount) => patchCorrection("sharpening", { amount })}
                                />
                                <SliderRow
                                    label="Threshold"
                                    value={options.sharpening.threshold}
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
                                                checked={options.rescan}
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

                            {error && (
                                <Box sx={{ p: 1.5 }}>
                                    <Alert severity="error">{error}</Alert>
                                </Box>
                            )}
                        </Box>
                    </Box>
                </Box>
            </Box>
        </Dialog>
    );
}
