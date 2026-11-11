import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { EventContext } from "./EventContext";
import type { CategoryEvent, EventStatus, ToastEvent } from "./EventContext";
import EventToasts from "../components/EventToasts";

const MAX_TOASTS = 4;

function categoryStatus(message: string): EventStatus {
    return message === "Idle" ? "idle" : "active";
}

const PROGRESS_RE = /^\((\d+)\/(\d+)\/(\d+)\)$/;

function parseProgress(message: string): { current: number; failure: number; total: number } {
    const match = PROGRESS_RE.exec(message);

    if (!match) {
        return { current: 0, failure: 0, total: 0 };
    }

    return { current: Number(match[1]), failure: Number(match[2]), total: Number(match[3]) };
}

export function EventProvider({ children }: { children: ReactNode }) {
    const [categories, setCategories] = useState<CategoryEvent[]>([
        { category: "Upload", current: 0, failure: 0, total: 0, status: "idle" },
    ]);
    const [toasts, setToasts] = useState<ToastEvent[]>([]);

    const setCategory = useCallback(
        (category: string, event: Partial<CategoryEvent>) => {
            setCategories((previous) => {
                const index = previous.findIndex((item) => item.category === category);

                if (index === -1) {
                    return [
                        ...previous,
                        { category, current: 0, failure: 0, total: 0, status: "idle", ...event },
                    ];
                }

                const next = [...previous];
                next[index] = { ...next[index], ...event };

                return next;
            });
        },
        [],
    );

    const removeCategory = useCallback((category: string) => {
        setCategories((previous) => previous.filter((item) => item.category !== category));
    }, []);

    const pushText = useCallback((message: string, level: "info" | "error" = "info") => {
        setToasts((previous) => {
            const toast: ToastEvent = { id: (previous.at(-1)?.id ?? 0) + 1, message, level };
            const next = [...previous, toast];

            return next.length > MAX_TOASTS ? next.slice(-MAX_TOASTS) : next;
        });
    }, []);

    const removeToast = useCallback((id: number) => {
        setToasts((previous) => previous.filter((toast) => toast.id !== id));
    }, []);

    useEffect(() => {
        const source = new EventSource("./api/events");

        source.addEventListener("pipeline", (event) => {
            const data = JSON.parse((event as MessageEvent).data) as Record<string, string>;

            for (const [key, value] of Object.entries(data)) {
                if (key === "Text") {
                    if (value) {
                        pushText(value, "info");
                    }
                    continue;
                }

                // An empty message means the category no longer applies
                // (e.g. a boundary download finished): drop it from the bar.
                if (!value) {
                    removeCategory(key);
                    continue;
                }

                setCategory(key, {
                    message: value,
                    status: categoryStatus(value),
                    ...parseProgress(value),
                });
            }
        });

        return () => source.close();
    }, [setCategory, pushText, removeCategory]);

    return (
        <EventContext.Provider value={{ categories, setCategory, pushText }}>
            {children}
            <EventToasts toasts={toasts} onRemove={removeToast} />
        </EventContext.Provider>
    );
}
