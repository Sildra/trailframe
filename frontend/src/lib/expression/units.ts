/** The unit syntax fields and metrics may carry: `80%`, `35mm`, `f/2.8`. */

export const KNOWN_SUFFIX_UNITS = new Set(["%", "mm", "s", "px", "B"]);

/** A unit written before its number, such as the aperture `f/2.8`. */
export function isPrefixUnit(unit: string | undefined): boolean {
    return !!unit && unit.endsWith("/");
}

/** Whether a bare word is a unit the language knows even without a schema. */
export function isKnownUnit(value: string): boolean {
    return KNOWN_SUFFIX_UNITS.has(value) || value.endsWith("/");
}
