export interface ObjectReference {
    width: number;
    height: number;
}

export interface HoveredObject {
    box: number[];
    reference: ObjectReference;
}

export interface ObjectDetectionBox {
    box: number[];
    confidence: number;
    label?: string;
}

/** All detections of one photo, shown at once when the Objects accordion is hovered. */
export interface HoveredObjects {
    reference: ObjectReference;
    boxes: ObjectDetectionBox[];
}

/** Either one row of the Objects list or the whole accordion. */
export type ObjectHover = HoveredObject | HoveredObjects;

/** A rectangular slice whose fill opacity is the highest confidence covering it. */
export interface ConfidenceRegion {
    box: number[];
    confidence: number;
}

/** The pixels-to-container mapping of an `object-fit: contain` image. */
export interface DisplayDims {
    nw: number;
    nh: number;
    scale: number;
    ox: number;
    oy: number;
}

export interface ObjectRect {
    x: number;
    y: number;
    width: number;
    height: number;
}

const DEDUPE_IOU = 0.9;

function normalizeBox(box: number[]): number[] | null {
    if (!Array.isArray(box) || box.length < 4) {
        return null;
    }

    const values = box.slice(0, 4).map(Number);

    if (values.some((value) => !Number.isFinite(value))) {
        return null;
    }

    const [x1, y1, x2, y2] = values;
    const left = Math.min(x1, x2);
    const top = Math.min(y1, y2);
    const right = Math.max(x1, x2);
    const bottom = Math.max(y1, y2);

    return right > left && bottom > top ? [left, top, right, bottom] : null;
}

function confidenceOf(value: number): number {
    return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
}

function iou(left: number[], right: number[]): number {
    const width = Math.min(left[2], right[2]) - Math.max(left[0], right[0]);
    const height = Math.min(left[3], right[3]) - Math.max(left[1], right[1]);

    if (width <= 0 || height <= 0) {
        return 0;
    }

    const intersection = width * height;
    const union =
        (left[2] - left[0]) * (left[3] - left[1]) +
        (right[2] - right[0]) * (right[3] - right[1]) -
        intersection;

    return union > 0 ? intersection / union : 0;
}

/** Drops near-identical detections, keeping the most confident one. */
export function dedupeObjectBoxes(boxes: ObjectDetectionBox[]): ObjectDetectionBox[] {
    const kept: ObjectDetectionBox[] = [];

    for (const entry of boxes) {
        const box = normalizeBox(entry.box);

        if (!box) {
            continue;
        }

        const confidence = confidenceOf(entry.confidence);
        const duplicate = kept.findIndex((candidate) => iou(candidate.box, box) >= DEDUPE_IOU);

        if (duplicate === -1) {
            kept.push({ ...entry, box, confidence });
        } else if (confidence > kept[duplicate].confidence) {
            kept[duplicate] = { ...entry, box, confidence };
        }
    }

    return kept;
}

/**
 * Splits the union of the boxes into rectangles whose opacity is the highest
 * confidence covering that rectangle, so partial overlaps never stack alpha.
 */
export function confidenceRegions(boxes: ObjectDetectionBox[]): ConfidenceRegion[] {
    const deduped = dedupeObjectBoxes(boxes);

    if (deduped.length === 0) {
        return [];
    }

    const xs = [...new Set(deduped.flatMap((entry) => [entry.box[0], entry.box[2]]))].sort((a, b) => a - b);
    const ys = [...new Set(deduped.flatMap((entry) => [entry.box[1], entry.box[3]]))].sort((a, b) => a - b);
    const regions: ConfidenceRegion[] = [];

    for (let column = 0; column < xs.length - 1; column += 1) {
        const x = (xs[column] + xs[column + 1]) / 2;
        const active = deduped.filter((entry) => entry.box[0] <= x && x < entry.box[2]);

        if (active.length === 0) {
            continue;
        }

        for (let row = 0; row < ys.length - 1; row += 1) {
            const y = (ys[row] + ys[row + 1]) / 2;
            let confidence = 0;

            for (const entry of active) {
                if (entry.box[1] <= y && y < entry.box[3]) {
                    confidence = Math.max(confidence, entry.confidence);
                }
            }

            if (confidence > 0) {
                regions.push({ box: [xs[column], ys[row], xs[column + 1], ys[row + 1]], confidence });
            }
        }
    }

    return regions;
}

/** The fixed alpha of the single-object highlight and the ceiling for the overview. */
export const OBJECT_OVERLAY_ALPHA = 0.15;

/** Scales the original fill alpha by confidence, so the photo stays visible. */
export function confidenceOpacity(confidence: number): number {
    return OBJECT_OVERLAY_ALPHA * confidenceOf(confidence);
}

/** Box outlines keep their full alpha, scaled only by confidence. */
export function confidenceStrokeOpacity(confidence: number): number {
    return confidenceOf(confidence);
}

/**
 * Maps a detection box, stored in the reference image space, onto the displayed
 * image. X and Y scale independently, so a differently sized or proportioned
 * served file still lines up. Returns `null` when the reference is unusable.
 */
export function objectRect(hovered: HoveredObject, dims: DisplayDims): ObjectRect | null {
    const { box, reference } = hovered;
    const [x1, y1, x2, y2] = box;
    const { nw, nh, scale, ox, oy } = dims;

    if (!reference || !reference.width || !reference.height) {
        return null;
    }

    const sx = (nw / reference.width) * scale;
    const sy = (nh / reference.height) * scale;

    return {
        x: ox + x1 * sx,
        y: oy + y1 * sy,
        width: (x2 - x1) * sx,
        height: (y2 - y1) * sy,
    };
}
