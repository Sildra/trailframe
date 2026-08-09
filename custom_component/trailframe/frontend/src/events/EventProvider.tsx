import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { EventContext } from "./EventContext";
import type { CategoryEvent, EventStatus, TextEvent } from "./EventContext";

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
    const [texts, setTexts] = useState<TextEvent[]>([]);

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

    const pushText = useCallback(
        (message: string, level: "info" | "error" = "info") => {
            setTexts((previous) => {
                const next = {
                    id: (previous.at(-1)?.id ?? 0) + 1,
                    message,
                    level,
                };

                if (previous.length === 0) {
                    return [next];
                }

                return [...previous.slice(0, -1), next];
            });
        },
        [],
    );

    useEffect(() => {
        const source = new EventSource("/api/events");

        source.addEventListener("pipeline", (event) => {
            const data = JSON.parse((event as MessageEvent).data) as Record<string, string>;

            for (const [key, value] of Object.entries(data)) {
                if (key === "Text") {
                    if (value) {
                        pushText(value, "info");
                    }
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
    }, [setCategory, pushText]);

    return (
        <EventContext.Provider value={{ categories, setCategory, texts, pushText }}>
            {children}
        </EventContext.Provider>
    );
}
