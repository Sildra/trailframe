export interface Projection {
    width: number;
    height: number;
    zoom: number;
    center: { lat: number; lon: number };
}

export function mercator(lat: number, lon: number): [number, number] {
    const latRad = (lat * Math.PI) / 180;
    const lonRad = (lon * Math.PI) / 180;

    return [lonRad / (2 * Math.PI) + 0.5, (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2];
}

export function project(lat: number, lon: number, projection: Projection): [number, number] {
    const [mx, my] = mercator(lat, lon);
    const [cx, cy] = mercator(projection.center.lat, projection.center.lon);
    const scale = Math.pow(2, projection.zoom) * 256;

    return [projection.width / 2 + (mx - cx) * scale, projection.height / 2 + (my - cy) * scale];
}
