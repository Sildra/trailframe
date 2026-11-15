export interface ProcessingLine {
    x1: number;
    y1: number;
    x2: number;
    y2: number;
}

export interface ProcessingPoint {
    x: number;
    y: number;
}

/**
 * A processing step in the two-stage layout.
 *
 * `details` is rendered verbatim: the backend already provides human-readable
 * labels and values with units. `meta` carries machine data for dedicated
 * frontend features (the tilt overlay) and is never shown.
 */
export interface ProcessingStep {
    step: string;
    summary: string;
    details: Record<string, string>;
    meta: Record<string, unknown>;
}

/** The data the viewer needs to draw the detected horizon and its target. */
export interface TiltOverlay {
    line: ProcessingLine;
    reference: ProcessingPoint;
}

function isNumber(value: unknown): value is number {
    return typeof value === "number" && Number.isFinite(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function stepLabel(step: string): string {
    if (!step) {
        return "Processing";
    }

    return step.charAt(0).toUpperCase() + step.slice(1);
}

function detailsBlock(value: unknown): Record<string, string> {
    if (!isRecord(value)) {
        return {};
    }

    const details: Record<string, string> = {};

    for (const [key, entry] of Object.entries(value)) {
        if (typeof entry === "string") {
            details[key] = entry;
        }
    }

    return details;
}

/** Turns the stored processing recipe into the two-stage shape. */
export function normalizeProcessing(entries: unknown[] | null | undefined): ProcessingStep[] {
    if (!Array.isArray(entries)) {
        return [];
    }

    return entries.flatMap((entry) => {
        if (!isRecord(entry)) {
            return [];
        }

        return [
            {
                step: typeof entry.step === "string" && entry.step !== "" ? entry.step : "processing",
                summary: typeof entry.summary === "string" ? entry.summary : "",
                details: detailsBlock(entry.details),
                meta: isRecord(entry.meta) ? entry.meta : {},
            },
        ];
    });
}

function parseLine(value: unknown): ProcessingLine | null {
    if (
        !isRecord(value) ||
        !isNumber(value.x1) ||
        !isNumber(value.y1) ||
        !isNumber(value.x2) ||
        !isNumber(value.y2)
    ) {
        return null;
    }

    return { x1: value.x1, y1: value.y1, x2: value.x2, y2: value.y2 };
}

function parsePoint(value: unknown): ProcessingPoint | null {
    if (!isRecord(value) || !isNumber(value.x) || !isNumber(value.y)) {
        return null;
    }

    return { x: value.x, y: value.y };
}

export function tiltOverlay(entry: ProcessingStep): TiltOverlay | null {
    if (entry.step !== "tilt") {
        return null;
    }

    const line = parseLine(entry.meta.line);

    if (!line) {
        return null;
    }

    const reference = parsePoint(entry.meta.reference_point) ?? {
        x: (line.x1 + line.x2) / 2,
        y: (line.y1 + line.y2) / 2,
    };

    return { line, reference };
}
