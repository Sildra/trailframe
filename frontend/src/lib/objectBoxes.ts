export interface ObjectReference {
    width: number;
    height: number;
}

export interface HoveredObject {
    box: number[];
    reference: ObjectReference;
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
