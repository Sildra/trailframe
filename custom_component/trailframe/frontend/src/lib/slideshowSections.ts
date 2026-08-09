export type MenuSection = "activities" | "groups" | "custom";

const MENU_SECTIONS: MenuSection[] = ["activities", "groups", "custom"];

const PARAM_ORDER = ["page", "section"];

export function isMenuSection(value: string): value is MenuSection {
    return MENU_SECTIONS.includes(value as MenuSection);
}

export function parseMenuSection(value: string | null): MenuSection {
    return value !== null && isMenuSection(value) ? value : "activities";
}

export function orderedSearch(params: URLSearchParams): string {
    const result = new URLSearchParams();

    for (const key of PARAM_ORDER) {
        const value = params.get(key);

        if (value !== null) {
            result.set(key, value);
        }
    }

    for (const [key, value] of params) {
        if (!PARAM_ORDER.includes(key)) {
            result.append(key, value);
        }
    }

    const query = result.toString();

    return query ? `?${query}` : "";
}

export function withMenuSection(search: URLSearchParams, section: MenuSection): string {
    const params = new URLSearchParams(search);
    params.set("section", section);

    return orderedSearch(params);
}
