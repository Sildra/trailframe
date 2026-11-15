import { useState } from "react";
import { Box, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";

import { normalizeProcessing, stepLabel, tiltOverlay, type TiltOverlay } from "../lib/processing";
import MetadataList from "./MetadataList";

interface ProcessingTreeProps {
    entries: unknown[] | null | undefined;
    onHoverTilt?: (tilt: TiltOverlay | null) => void;
}

/**
 * Two-stage processing recipe: each step is a headline row (name + summary)
 * that expands into its detail rows. Hovering a tilt step asks the viewer to
 * draw the detected horizon and the corrected target.
 */
export default function ProcessingTree({ entries, onHoverTilt }: ProcessingTreeProps) {
    const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
    const steps = normalizeProcessing(entries);

    if (steps.length === 0) {
        return <Typography sx={{ fontSize: 13, color: "text.secondary" }}>No processing recorded.</Typography>;
    }

    const toggle = (index: number) => {
        setCollapsed((previous) => {
            const next = new Set(previous);

            if (next.has(index)) {
                next.delete(index);
            } else {
                next.add(index);
            }

            return next;
        });
    };

    return (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 0.25 }}>
            {steps.map((entry, index) => {
                const expanded = !collapsed.has(index);
                const overlay = tiltOverlay(entry);
                const details = Object.entries(entry.details);

                return (
                    <Box key={`${entry.step}-${index}`}>
                        <Box
                            onClick={() => toggle(index)}
                            onMouseEnter={overlay ? () => onHoverTilt?.(overlay) : undefined}
                            onMouseLeave={overlay ? () => onHoverTilt?.(null) : undefined}
                            sx={{
                                display: "flex",
                                alignItems: "center",
                                gap: 0.5,
                                px: 0.5,
                                borderRadius: 1,
                                cursor: "pointer",
                                "&:hover": { bgcolor: "action.hover" },
                            }}
                        >
                            <ExpandMoreIcon
                                fontSize="small"
                                sx={{
                                    color: "text.secondary",
                                    transform: expanded ? "rotate(0deg)" : "rotate(-90deg)",
                                    transition: "transform 0.15s",
                                }}
                            />
                            <Typography sx={{ fontWeight: 600, fontSize: 13 }}>{stepLabel(entry.step)}</Typography>
                            {entry.summary && (
                                <>
                                    <Box sx={{ flex: 1, borderBottom: 1, borderColor: "divider", mx: 0.5 }} />
                                    <Typography sx={{ fontSize: 13, color: "text.secondary" }}>
                                        {entry.summary}
                                    </Typography>
                                </>
                            )}
                        </Box>
                        {expanded && details.length > 0 && (
                            <Box sx={{ pl: 3.5, pt: 0.25, pb: 0.5 }}>
                                <MetadataList entries={details} />
                            </Box>
                        )}
                    </Box>
                );
            })}
        </Box>
    );
}
