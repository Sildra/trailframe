import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Definition } from "../lib/rules";
import type { components } from "../api/generated/schema";

export type PreviewResult = components["schemas"]["RulePreviewResponse"];

export interface PreviewState {
    key: string;
    loading: boolean;
    result: PreviewResult | null;
    error: string | null;
}

interface Pending {
    key: string;
    tag: string;
    definition: Definition;
}

const DEBOUNCE = 450;

/**
 * Preview a draft rule with one request in flight at a time.
 *
 * The caller passes only locally valid definitions. Identical definitions are
 * not re-queried, and a change made while a request is in flight is coalesced
 * to the latest one when it finishes.
 */
export function useRulePreview(tag: string, definition: Definition | null, enabled = true) {
    const [state, setState] = useState<PreviewState>({ key: "", loading: false, result: null, error: null });
    const lastKey = useRef("");
    const inFlight = useRef(false);
    const pending = useRef<Pending | null>(null);
    const timer = useRef<number | null>(null);
    const controller = useRef<AbortController | null>(null);
    const mounted = useRef(true);

    useEffect(() => {
        mounted.current = true;

        return () => {
            mounted.current = false;
            controller.current?.abort();

            if (timer.current !== null) {
                window.clearTimeout(timer.current);
            }
        };
    }, []);

    useEffect(() => {
        if (!enabled || definition === null) {
            pending.current = null;

            if (timer.current !== null) {
                window.clearTimeout(timer.current);
                timer.current = null;
            }

            return;
        }

        const key = `${tag}\u0000${JSON.stringify(definition)}`;

        if (key === lastKey.current) {
            // The draft went back to the definition already previewed; drop any
            // newer preview still queued behind the request in flight.
            pending.current = null;
            return;
        }

        if (key === pending.current?.key) {
            return;
        }

        pending.current = { key, tag, definition };

        const flush = () => {
            const next = pending.current;

            if (!next || inFlight.current || next.key === lastKey.current) {
                return;
            }

            if (!mounted.current) {
                return;
            }

            lastKey.current = next.key;
            inFlight.current = true;
            controller.current = new AbortController();
            setState({ key: next.key, loading: true, result: null, error: null });

            api.POST("/api/rules/preview", {
                body: { tag: next.tag, definition: next.definition, limit: 24 },
                signal: controller.current.signal,
            })
                .then(({ data, error: failure }) => {
                    if (!mounted.current) {
                        return;
                    }

                    if (failure || !data) {
                        setState({ key: next.key, loading: false, result: null, error: "The preview could not be loaded." });
                    } else {
                        setState({ key: next.key, loading: false, result: data, error: null });
                    }
                })
                .catch(() => {
                    if (mounted.current) {
                        setState({ key: next.key, loading: false, result: null, error: "The preview could not be loaded." });
                    }
                })
                .finally(() => {
                    inFlight.current = false;

                    // Pick up the latest change queued while the request ran.
                    const queued = pending.current;

                    if (mounted.current && queued && queued.key !== lastKey.current) {
                        flush();
                    }
                });
        };

        if (timer.current !== null) {
            window.clearTimeout(timer.current);
        }

        timer.current = window.setTimeout(flush, DEBOUNCE);

        return () => {
            if (timer.current !== null) {
                window.clearTimeout(timer.current);
            }
        };
    }, [tag, definition, enabled]);

    return state;
}
