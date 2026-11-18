import type { ProcessingLine, ProcessingPoint } from "./processing";
import type { CropMode } from "./reprocess";

export interface Size {
    width: number;
    height: number;
}

export interface Rect {
    x: number;
    y: number;
    width: number;
    height: number;
}

export interface Segment {
    x1: number;
    y1: number;
    x2: number;
    y2: number;
}

/** The detected horizon and reference point, in normalized (0..1) original coordinates. */
export interface PreviewTilt {
    line: ProcessingLine | null;
    reference: ProcessingPoint | null;
    /** The estimate recorded on the tilt step, in degrees, when there is no line. */
    detectedAngle: number | null;
}

export interface PreviewOptions {
    /** Correction angle applied by the backend (PIL convention, positive = counter-clockwise). */
    angle: number;
    cropMode: CropMode;
    /** Main target size (longest edge, px). */
    target: number;
}

/** Everything the SVG preview needs, in original pixel coordinates. */
export interface PreviewModel {
    /** Placement of the image inside the rotating group, centered on the origin. */
    image: Rect;
    /** Rotated canvas (expanded) size. */
    canvas: Size;
    /** Padding around the canvas for the crop border and shadow. */
    padding: number;
    /** Crop rectangle, centered in the canvas. */
    crop: Rect;
    /** Whether the crop actually trims the expanded canvas. */
    trims: boolean;
    /** Crop size in original pixels. */
    cropSize: Size;
    /** Output (main target) size. */
    output: Size;
    /** Detected horizon, in centered image coordinates (draw inside the rotating group). */
    horizon: Segment | null;
    /** Level target line, in canvas coordinates. */
    level: Segment;
    /** Reference marker, in canvas coordinates. */
    marker: { x: number; y: number };
    /** Correction angle, in degrees (PIL convention). */
    angle: number;
}

const EPSILON = 1e-6;

function radians(angle: number): number {
    return (angle * Math.PI) / 180;
}

/** The axis-aligned bounding box of a `width × height` rectangle rotated by `angle`. */
export function rotatedSize(width: number, height: number, angle: number): Size {
    const theta = radians(Math.abs(angle) % 180);
    const sin = Math.abs(Math.sin(theta));
    const cos = Math.abs(Math.cos(theta));

    return { width: width * cos + height * sin, height: width * sin + height * cos };
}

/**
 * Largest axis-aligned rectangle without empty borders, after rotating by `angle`.
 *
 * Port of `largest_inscribed_rectangle` from the backend, so the preview shows
 * the same area the crop processor keeps.
 */
export function largestInscribedRectangle(width: number, height: number, angle: number): Size {
    if (width <= 0 || height <= 0) {
        return { width: Math.max(1, width), height: Math.max(1, height) };
    }

    let theta = radians(Math.abs(angle) % 180);

    if (theta > Math.PI / 2) {
        theta = Math.PI - theta;
    }

    const sin = Math.abs(Math.sin(theta));
    const cos = Math.abs(Math.cos(theta));

    if (sin < 1e-9 || cos < 1e-9) {
        return { width, height };
    }

    const widthIsLonger = width >= height;
    const longSide = widthIsLonger ? width : height;
    const shortSide = widthIsLonger ? height : width;

    if (shortSide <= 2 * sin * cos * longSide || Math.abs(sin - cos) < 1e-9) {
        const half = 0.5 * shortSide;

        return widthIsLonger
            ? { width: half / sin, height: half / cos }
            : { width: half / cos, height: half / sin };
    }

    const cos2a = cos * cos - sin * sin;

    return {
        width: (width * cos - height * sin) / cos2a,
        height: (height * cos - width * sin) / cos2a,
    };
}

/** The area left after the tilt/crop steps, in the given source pixels. */
export function cropSize(width: number, height: number, angle: number, cropMode: CropMode): Size {
    if (cropMode === "none" || Math.abs(angle) < EPSILON) {
        return rotatedSize(width, height, angle);
    }

    return largestInscribedRectangle(width, height, angle);
}

/** The size of the written main alternative. */
export function outputSize(crop: Size, target: number, sourceLongest: number): Size {
    const longest = Math.max(crop.width, crop.height);

    if (longest <= 0) {
        return { width: 0, height: 0 };
    }

    const outputLongest = sourceLongest >= target ? target : longest;
    const scale = outputLongest / longest;

    return {
        width: Math.max(1, Math.round(crop.width * scale)),
        height: Math.max(1, Math.round(crop.height * scale)),
    };
}

/** Screen slope of a normalized line, in degrees, normalized to (-90, 90]. */
export function lineAngle(line: ProcessingLine, image: Size): number {
    const dx = (line.x2 - line.x1) * image.width;
    const dy = (line.y2 - line.y1) * image.height;
    const degrees = (Math.atan2(dy, dx) * 180) / Math.PI;

    return (((degrees + 90) % 180) + 180) % 180 - 90;
}

/**
 * The angle the backend applies to the photo.
 *
 * Automatic mode only corrects when the stored decision applied the estimate;
 * manual mode uses the entered angle; off applies nothing.
 */
export function effectiveAngle(
    mode: "auto" | "off" | "manual",
    manualAngle: number,
    detectedAngle: number | null,
    applied: boolean,
): number {
    if (mode === "off") {
        return 0;
    }

    if (mode === "manual") {
        return Number.isFinite(manualAngle) ? manualAngle : 0;
    }

    return applied && detectedAngle !== null ? detectedAngle : 0;
}

function centered(point: ProcessingPoint, image: Size): { x: number; y: number } {
    return { x: point.x * image.width - image.width / 2, y: point.y * image.height - image.height / 2 };
}

/** Rotates a centered point by the same visual rotation the SVG group applies (`-angle`). */
function toCanvas(point: { x: number; y: number }, angle: number, canvas: Size): { x: number; y: number } {
    const theta = radians(angle);
    const cos = Math.cos(theta);
    const sin = Math.sin(theta);

    return {
        x: canvas.width / 2 + point.x * cos + point.y * sin,
        y: canvas.height / 2 - point.x * sin + point.y * cos,
    };
}

/**
 * Builds the preview geometry from the oriented original size and the tilt data.
 *
 * All coordinates are in original pixels, so the size captions are exact; the
 * SVG scales them down to fit the available space.
 */
export function buildPreview(image: Size, tilt: PreviewTilt, options: PreviewOptions): PreviewModel {
    const canvas = rotatedSize(image.width, image.height, options.angle);
    const crop = cropSize(image.width, image.height, options.angle, options.cropMode);
    const cropWidth = Math.min(canvas.width, Math.max(1, crop.width));
    const cropHeight = Math.min(canvas.height, Math.max(1, crop.height));
    const cropSizeInPixels =
        options.cropMode === "none"
            ? { width: Math.max(1, Math.round(canvas.width)), height: Math.max(1, Math.round(canvas.height)) }
            : {
                  width: Math.max(1, Math.min(Math.round(image.width), Math.round(cropWidth))),
                  height: Math.max(1, Math.min(Math.round(image.height), Math.round(cropHeight))),
              };
    const output = outputSize(cropSizeInPixels, options.target, Math.max(image.width, image.height));

    const reference =
        tilt.reference ??
        (tilt.line
            ? {
                  x: (tilt.line.x1 + tilt.line.x2) / 2,
                  y: (tilt.line.y1 + tilt.line.y2) / 2,
              }
            : { x: 0.5, y: 0.5 });
    const referenceCentered = centered(reference, image);
    const referenceOnCanvas = toCanvas(referenceCentered, options.angle, canvas);

    const horizonAngle = tilt.line ? lineAngle(tilt.line, image) : tilt.detectedAngle;
    const diagonal = Math.hypot(image.width, image.height);
    const horizon =
        horizonAngle === null
            ? null
            : (() => {
                  const theta = radians(horizonAngle);
                  const dx = Math.cos(theta) * diagonal;
                  const dy = Math.sin(theta) * diagonal;

                  return {
                      x1: referenceCentered.x - dx,
                      y1: referenceCentered.y - dy,
                      x2: referenceCentered.x + dx,
                      y2: referenceCentered.y + dy,
                  };
              })();

    return {
        image: {
            x: -image.width / 2,
            y: -image.height / 2,
            width: image.width,
            height: image.height,
        },
        canvas,
        padding: Math.max(canvas.width, canvas.height) * 0.04,
        crop: {
            x: (canvas.width - cropWidth) / 2,
            y: (canvas.height - cropHeight) / 2,
            width: cropWidth,
            height: cropHeight,
        },
        trims: cropWidth < canvas.width - 1 || cropHeight < canvas.height - 1,
        cropSize: cropSizeInPixels,
        output,
        horizon,
        level: {
            x1: referenceOnCanvas.x - diagonal / 2,
            y1: referenceOnCanvas.y,
            x2: referenceOnCanvas.x + diagonal / 2,
            y2: referenceOnCanvas.y,
        },
        marker: referenceOnCanvas,
        angle: options.angle,
    };
}
