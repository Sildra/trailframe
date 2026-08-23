import { createContext, useContext } from "react";

export type EventStatus = "active" | "success" | "failure" | "idle";

export interface CategoryEvent {
    category: string;
    current: number;
    failure: number;
    total: number;
    status: EventStatus;
    message?: string;
}

export interface TextEvent {
    id: number;
    message: string;
    level: "info" | "error";
}

export interface EventContextValue {
    categories: CategoryEvent[];
    setCategory: (category: string, event: Partial<CategoryEvent>) => void;
    texts: TextEvent[];
    pushText: (message: string, level?: "info" | "error") => void;
}

export const EventContext = createContext<EventContextValue | null>(null);

export function useEvents() {
    const context = useContext(EventContext);

    if (!context) {
        throw new Error("useEvents must be used within EventProvider");
    }

    return context;
}
