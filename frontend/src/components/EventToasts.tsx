import { useEffect, useState } from "react";
import { Alert, Box, Grow } from "@mui/material";
import type { ToastEvent } from "../events/EventContext";

const AUTO_HIDE_MS: Record<ToastEvent["level"], number> = {
    info: 5000,
    error: 8000,
};

interface ToastItemProps {
    toast: ToastEvent;
    onRemove: (id: number) => void;
}

function ToastItem({ toast, onRemove }: ToastItemProps) {
    const [closing, setClosing] = useState(false);

    useEffect(() => {
        const timer = window.setTimeout(() => setClosing(true), AUTO_HIDE_MS[toast.level]);

        return () => window.clearTimeout(timer);
    }, [toast.id, toast.level]);

    return (
        <Grow in={!closing} onExited={() => onRemove(toast.id)}>
            <Alert
                severity={toast.level === "error" ? "error" : "info"}
                variant="filled"
                onClose={() => setClosing(true)}
                sx={{ pointerEvents: "auto", boxShadow: 3 }}
            >
                {toast.message}
            </Alert>
        </Grow>
    );
}

interface EventToastsProps {
    toasts: ToastEvent[];
    onRemove: (id: number) => void;
}

export default function EventToasts({ toasts, onRemove }: EventToastsProps) {
    return (
        <Box
            sx={{
                position: "fixed",
                bottom: (theme) => theme.spacing(2),
                right: (theme) => theme.spacing(2),
                zIndex: (theme) => theme.zIndex.snackbar,
                display: "flex",
                flexDirection: "column",
                alignItems: "flex-end",
                gap: 1,
                maxWidth: 360,
                pointerEvents: "none",
            }}
        >
            {toasts.map((toast) => (
                <ToastItem key={toast.id} toast={toast} onRemove={onRemove} />
            ))}
        </Box>
    );
}
