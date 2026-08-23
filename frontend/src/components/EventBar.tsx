import { Box, LinearProgress, Typography } from "@mui/material";
import { useEvents } from "../events/EventContext";
import type { EventStatus } from "../events/EventContext";

const STATUS_LABELS: Record<EventStatus, string> = {
    active: "Running",
    success: "Done",
    failure: "Failed",
    idle: "Idle",
};

export default function EventBar() {
    const { categories, texts } = useEvents();
    const recentTexts = texts.slice(-5);
    const boxCount = categories.length + 1;

    return (
        <Box
            component="footer"
            sx={{
                display: "grid",
                gridTemplateColumns: `repeat(${boxCount}, 1fr)`,
                borderTop: 1,
                borderColor: "divider",
                bgcolor: "action.hover",
                flexShrink: 0,
                "& > :first-of-type": { borderLeft: "none" },
            }}
        >
            {categories.map(({ category, current, failure, total, status, message }) => {
                const successPercent = total > 0 ? (current / total) * 100 : 0;
                const failurePercent = total > 0 ? (failure / total) * 100 : 0;
                const meta =
                    total > 0
                        ? `(${[current, failure, total].filter((value) => value > 0).join("/")})`
                        : (message ?? STATUS_LABELS[status]);

                return (
                    <Box
                        key={category}
                        sx={{
                            boxSizing: "border-box",
                            minWidth: 0,
                            px: 1.5,
                            py: 0.75,
                            borderLeft: 1,
                            borderColor: "divider",
                        }}
                    >
                        <Box
                            sx={{
                                display: "flex",
                                alignItems: "baseline",
                                justifyContent: "space-between",
                                gap: 1,
                                mb: 0.25,
                            }}
                        >
                            <Typography sx={{ fontWeight: 600, fontSize: 12 }}>{category}</Typography>
                            <Typography sx={{ color: "text.secondary", whiteSpace: "nowrap", fontSize: 12 }}>
                                {meta}
                            </Typography>
                        </Box>
                        <Box sx={{ position: "relative", height: 4, borderRadius: 1, bgcolor: "divider", overflow: "hidden" }}>
                            {successPercent > 0 && (
                                <LinearProgress
                                    variant="determinate"
                                    value={successPercent}
                                    sx={{ position: "absolute", inset: 0 }}
                                />
                            )}
                            {failurePercent > 0 && (
                                <LinearProgress
                                    variant="determinate"
                                    value={failurePercent}
                                    color="error"
                                    sx={{ position: "absolute", inset: 0 }}
                                />
                            )}
                        </Box>
                    </Box>
                );
            })}
            <Box
                sx={{
                    boxSizing: "border-box",
                    minWidth: 0,
                    px: 1.5,
                    py: 0.5,
                    borderLeft: 1,
                    borderColor: "divider",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "flex-end",
                    justifyContent: "center",
                    gap: 0.25,
                    overflow: "hidden",
                }}
            >
                {recentTexts.map((text) => (
                    <Typography
                        key={text.id}
                        sx={{
                            fontSize: 12,
                            whiteSpace: "nowrap",
                            color: text.level === "error" ? "error.main" : "text.primary",
                        }}
                    >
                        {text.message}
                    </Typography>
                ))}
            </Box>
        </Box>
    );
}
