import { useState } from "react";
import {
    Alert,
    Box,
    Button,
    Chip,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControl,
    FormControlLabel,
    FormLabel,
    MenuItem,
    Radio,
    RadioGroup,
    Stack,
    Switch,
    TextField,
    Typography,
} from "@mui/material";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";
import {
    MAX_MANUAL_ANGLE,
    MAX_TARGETS,
    MAX_TARGET_SIZE,
    MIN_TARGET_SIZE,
    defaultReprocessOptions,
    toReprocessPayload,
    validateOptions,
    type CropMode,
    type ReprocessOptions,
    type TiltMode,
} from "../lib/reprocess";

type Photo = components["schemas"]["PhotoDetail"];

interface ReprocessDialogProps {
    photo: Photo;
    onClose: () => void;
    onUpdated: (photo: Photo) => void;
}

/** A schematic of the horizon: the dashed line is level, the red line is the angle. */
function HorizonDiagram({ angle }: { angle: number }) {
    const width = 240;
    const height = 80;
    const centerX = width / 2;
    const centerY = height / 2;
    const half = width / 2 - 20;
    const radians = (angle * Math.PI) / 180;
    const dx = Math.cos(radians) * half;
    const dy = -Math.sin(radians) * half;

    return (
        <Box sx={{ color: "text.secondary", mt: 1 }}>
            <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} aria-hidden="true">
                <line
                    x1={16}
                    y1={centerY}
                    x2={width - 16}
                    y2={centerY}
                    stroke="currentColor"
                    strokeOpacity={0.35}
                    strokeDasharray="5 4"
                />
                <line
                    x1={centerX - dx}
                    y1={centerY - dy}
                    x2={centerX + dx}
                    y2={centerY + dy}
                    stroke="#ff5252"
                    strokeWidth={2}
                />
            </svg>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", textAlign: "center" }}>
                {angle === 0 ? "Level horizon" : `Horizon ${angle > 0 ? "+" : ""}${angle.toFixed(2)}°`}
            </Typography>
        </Box>
    );
}

export default function ReprocessDialog({ photo, onClose, onUpdated }: ReprocessDialogProps) {
    const [options, setOptions] = useState<ReprocessOptions>(() => defaultReprocessOptions(photo));
    const [newSize, setNewSize] = useState("");
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const update = (patch: Partial<ReprocessOptions>) =>
        setOptions((current) => ({ ...current, ...patch }));

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
        <Dialog open onClose={saving ? undefined : onClose} maxWidth="md" fullWidth>
            <DialogTitle>Adjust processing</DialogTitle>
            <DialogContent dividers>
                <Box sx={{ display: "flex", flexDirection: { xs: "column", sm: "row" }, gap: 2 }}>
                    <Box sx={{ flex: "1 1 45%", minWidth: 0 }}>
                        <Box
                            sx={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                bgcolor: "action.hover",
                                minHeight: 160,
                                overflow: "hidden",
                            }}
                        >
                            {photo.id != null && (
                                <img
                                    src={`./api/photos/${photo.id}/image`}
                                    alt={photo.filename ?? "Photo"}
                                    style={{ display: "block", maxWidth: "100%", maxHeight: 260, objectFit: "contain" }}
                                />
                            )}
                        </Box>
                        <HorizonDiagram angle={options.tiltMode === "off" ? 0 : options.angle} />
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                            {photo.filename ?? photo.path}
                        </Typography>
                    </Box>
                    <Stack spacing={2} sx={{ flex: "1 1 55%", minWidth: 0 }}>
                        <Box>
                            <FormLabel component="legend" sx={{ fontSize: 13, mb: 1 }}>
                                Outputs
                            </FormLabel>
                            <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 0.5 }}>
                                {options.alternatives.map((size) => (
                                    <Chip
                                        key={size}
                                        label={`${size} px`}
                                        color={size === options.main ? "primary" : "default"}
                                        onDelete={
                                            options.alternatives.length > 1 ? () => removeTarget(size) : undefined
                                        }
                                    />
                                ))}
                            </Stack>
                            <Stack direction="row" spacing={1} sx={{ alignItems: "center", mt: 1 }}>
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
                                    slotProps={{ htmlInput: { min: MIN_TARGET_SIZE, max: MAX_TARGET_SIZE, step: 1 } }}
                                    sx={{ width: 130 }}
                                />
                                <Button size="small" onClick={addTarget} disabled={newSize === ""}>
                                    Add
                                </Button>
                                <TextField
                                    select
                                    size="small"
                                    label="Main size"
                                    value={options.main}
                                    onChange={(event) => update({ main: Number(event.target.value) })}
                                    sx={{ minWidth: 130 }}
                                >
                                    {options.alternatives.map((size) => (
                                        <MenuItem key={size} value={size}>
                                            {size} px
                                        </MenuItem>
                                    ))}
                                </TextField>
                            </Stack>
                            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                                Longest edge, in pixels ({MIN_TARGET_SIZE}–{MAX_TARGET_SIZE}). The main size is what the
                                gallery and the scanners use.
                            </Typography>
                        </Box>
                        <Box>
                            <FormLabel component="legend" sx={{ fontSize: 13 }}>
                                Horizon
                            </FormLabel>
                            <FormControl>
                                <RadioGroup
                                    row
                                    value={options.tiltMode}
                                    onChange={(event) => update({ tiltMode: event.target.value as TiltMode })}
                                >
                                    <FormControlLabel value="auto" control={<Radio size="small" />} label="Automatic" />
                                    <FormControlLabel value="off" control={<Radio size="small" />} label="Off" />
                                    <FormControlLabel value="manual" control={<Radio size="small" />} label="Manual" />
                                </RadioGroup>
                            </FormControl>
                            <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                                <TextField
                                    size="small"
                                    type="number"
                                    label="Angle"
                                    value={options.angle}
                                    disabled={options.tiltMode !== "manual"}
                                    onChange={(event) =>
                                        update({ angle: event.target.value === "" ? 0 : Number(event.target.value) })
                                    }
                                    slotProps={{
                                        htmlInput: {
                                            step: 0.1,
                                            min: -MAX_MANUAL_ANGLE,
                                            max: MAX_MANUAL_ANGLE,
                                        },
                                    }}
                                    sx={{ width: 130 }}
                                />
                                <Typography sx={{ fontSize: 13 }}>degrees</Typography>
                            </Stack>
                            <TextField
                                select
                                size="small"
                                label="Crop"
                                value={options.cropMode}
                                onChange={(event) => update({ cropMode: event.target.value as CropMode })}
                                helperText="The maximum valid rectangle trims the rotated borders."
                                sx={{ mt: 1, minWidth: 250 }}
                            >
                                <MenuItem value="maximum_valid_rectangle">Maximum valid rectangle</MenuItem>
                                <MenuItem value="none">Keep the expanded canvas</MenuItem>
                            </TextField>
                        </Box>
                        <Box>
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
                                Recomputes object and duplicate detection on the new main image. EXIF, tags, location
                                and dates are kept.
                            </Typography>
                        </Box>
                        {error && <Alert severity="error">{error}</Alert>}
                    </Stack>
                </Box>
            </DialogContent>
            <DialogActions>
                <Button
                    onClick={() => {
                        setOptions(defaultReprocessOptions(photo));
                        setError(null);
                    }}
                    disabled={saving}
                >
                    Reset
                </Button>
                <Box sx={{ flex: 1 }} />
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
            </DialogActions>
        </Dialog>
    );
}
