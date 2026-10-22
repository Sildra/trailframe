import { useEffect } from "react";
import { useMap } from "react-leaflet";

interface Size {
    width: number;
    height: number;
}

/**
 * Leaflet measures its container once and caches the result; it only re-measures
 * when the window itself is resized. When the surrounding layout changes — e.g.
 * the section pane of the Tools/Map page is collapsed — the container grows but
 * Leaflet keeps painting the old, narrower viewport, so the tiles and the
 * overlays only cover the previous area.
 *
 * This component watches the map container and forces a re-measure so the map
 * fills the new area.
 */
export default function MapResizer() {
    const map = useMap();

    useEffect(() => {
        const container = map.getContainer();
        let frame = 0;
        let previous: Size = { width: container.clientWidth, height: container.clientHeight };

        const observer = new ResizeObserver(() => {
            const width = container.clientWidth;
            const height = container.clientHeight;

            if (width === previous.width && height === previous.height) {
                return;
            }

            const old = previous;
            previous = { width, height };

            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(() => {
                map.invalidateSize({ animate: false });

                // Leaflet skips the re-layout when the centre of the container
                // stays in place (a change of a single pixel). Force a view
                // reset in that case, otherwise the tiles keep the old extent.
                const centreMoved =
                    Math.round(old.width / 2) !== Math.round(width / 2) ||
                    Math.round(old.height / 2) !== Math.round(height / 2);

                if (!centreMoved) {
                    map.setView(map.getCenter(), map.getZoom(), { animate: false });
                }
            });
        });

        observer.observe(container);

        return () => {
            cancelAnimationFrame(frame);
            observer.disconnect();
        };
    }, [map]);

    return null;
}
