import type { components } from "../api/generated/schema";

export type TagNode = components["schemas"]["TagNode"];
export type TagEntry = components["schemas"]["TagPayload"];

export const TAG_SEPARATOR = "/";

/** The last segment of a tag path ("Church" for "Architecture/Building/Church"). */
export function tagName(path: string): string {
    const index = path.lastIndexOf(TAG_SEPARATOR);

    return index === -1 ? path : path.slice(index + 1);
}

/** The path of the parent of a tag ("" for a root tag). */
export function tagParent(path: string): string {
    const index = path.lastIndexOf(TAG_SEPARATOR);

    return index === -1 ? "" : path.slice(0, index);
}

/** Whether a path is the given path or one of its descendants. */
export function isTagUnder(path: string, parent: string): boolean {
    return path === parent || path.startsWith(parent + TAG_SEPARATOR);
}

/** The canonical form of a tag path: trimmed segments, single separators. */
export function normalizeTagPath(raw: string): string {
    return raw
        .split(TAG_SEPARATOR)
        .map((segment) => segment.trim())
        .filter((segment) => segment.length > 0)
        .join(TAG_SEPARATOR);
}

/** Flatten a tag tree into the payload of the bulk editor. */
export function flattenTags(nodes: TagNode[]): TagEntry[] {
    const entries: TagEntry[] = [];

    const walk = (list: TagNode[]) => {
        for (const node of list) {
            entries.push({ id: node.id ?? null, path: node.path, description: node.description ?? null });
            walk(node.children ?? []);
        }
    };

    walk(nodes);

    return entries;
}

interface MutableTagNode {
    id: number | null;
    name: string;
    path: string;
    depth: number;
    description: string | null;
    count: number;
    total: number;
    children: MutableTagNode[];
}

/** Rebuild a tree from a flat list of paths (orphans become roots). */
export function buildTagTree(entries: TagEntry[]): TagNode[] {
    const nodes = new Map<string, MutableTagNode>();

    for (const entry of entries) {
        nodes.set(entry.path, {
            id: entry.id ?? null,
            name: tagName(entry.path),
            path: entry.path,
            depth: entry.path.split(TAG_SEPARATOR).length - 1,
            description: entry.description ?? null,
            count: 0,
            total: 0,
            children: [],
        });
    }

    const roots: MutableTagNode[] = [];

    for (const entry of entries) {
        const node = nodes.get(entry.path);

        if (!node) {
            continue;
        }

        const parent = nodes.get(tagParent(entry.path));

        if (parent && parent !== node) {
            parent.children.push(node);
        } else {
            roots.push(node);
        }
    }

    return roots as unknown as TagNode[];
}

/** A tag name is a single segment: separators are not allowed in it. */
export function sanitizeTagName(name: string): string {
    return name
        .split(TAG_SEPARATOR)
        .map((segment) => segment.trim())
        .filter((segment) => segment.length > 0)
        .join(" ");
}

/** The path a tag takes when its last segment is replaced by `name`. */
export function renamedTagPath(path: string, name: string): string {
    const trimmed = sanitizeTagName(name);

    if (!trimmed) {
        return path;
    }

    const parent = tagParent(path);

    return parent ? `${parent}${TAG_SEPARATOR}${trimmed}` : trimmed;
}

/** Rename a tag: the node and every descendant follow the new name. */
export function renameTag(entries: TagEntry[], path: string, name: string): TagEntry[] {
    const trimmed = sanitizeTagName(name);

    if (!trimmed) {
        return entries;
    }

    const parent = tagParent(path);
    const target = parent ? `${parent}${TAG_SEPARATOR}${trimmed}` : trimmed;

    if (target === path) {
        return entries;
    }

    return entries.map((entry) => {
        if (entry.path === path) {
            return { ...entry, path: target };
        }

        if (isTagUnder(entry.path, path)) {
            return { ...entry, path: target + entry.path.slice(path.length) };
        }

        return entry;
    });
}

/** The path a tag takes when it is moved under `parent` (empty for a root tag). */
export function movedTagPath(path: string, parent: string): string {
    const trimmed = normalizeTagPath(parent);

    return trimmed ? `${trimmed}${TAG_SEPARATOR}${tagName(path)}` : tagName(path);
}

/** Move a tag under another parent (or to the root when the parent is empty). */
export function moveTag(entries: TagEntry[], path: string, parent: string): TagEntry[] {
    const target = movedTagPath(path, parent);

    if (target === path || isTagUnder(target, path)) {
        return entries;
    }

    return entries.map((entry) => {
        if (entry.path === path) {
            return { ...entry, path: target };
        }

        if (isTagUnder(entry.path, path)) {
            return { ...entry, path: target + entry.path.slice(path.length) };
        }

        return entry;
    });
}

/** Remove a tag and every descendant from the vocabulary. */
export function removeTag(entries: TagEntry[], path: string): TagEntry[] {
    return entries.filter((entry) => !isTagUnder(entry.path, path));
}

/** The descendants of a tag, including the tag itself. */
export function tagSubtree(entries: TagEntry[], path: string): TagEntry[] {
    return entries.filter((entry) => isTagUnder(entry.path, path));
}

/** Add a tag under a parent (a root tag when the parent is empty). */
export function addTag(entries: TagEntry[], parent: string, name: string): TagEntry[] {
    const trimmed = name.trim();

    if (!trimmed) {
        return entries;
    }

    const path = parent ? `${parent}${TAG_SEPARATOR}${trimmed}` : trimmed;

    if (entries.some((entry) => entry.path === path)) {
        return entries;
    }

    return [...entries, { id: null, path, description: null }];
}

/** Every path of the vocabulary, sorted. */
export function tagPaths(entries: TagEntry[]): string[] {
    return entries.map((entry) => entry.path).sort((left, right) => left.localeCompare(right));
}

export interface TagCounts {
    /** Photos tagged with exactly this path. */
    count: number;
    /** Photos tagged with this path or one of its descendants. */
    total: number;
}

export interface TagRow {
    id: number | null;
    name: string;
    path: string;
    parent: string;
    depth: number;
    description: string | null;
    count: number;
    total: number;
}

/** Flatten a tag tree into the rows of the overview table. */
export function tagRows(tree: TagNode[], counts: Record<number, TagCounts>): TagRow[] {
    const totals = new Map<string, number>();

    const computeTotal = (node: TagNode): number => {
        const count = node.id != null ? (counts[node.id]?.count ?? 0) : 0;
        const total = count + (node.children ?? []).reduce((sum, child) => sum + computeTotal(child), 0);

        totals.set(node.path, total);

        return total;
    };

    tree.forEach(computeTotal);

    const rows: TagRow[] = [];

    const walk = (nodes: TagNode[]) => {
        for (const node of nodes) {
            rows.push({
                id: node.id ?? null,
                name: node.name,
                path: node.path,
                parent: tagParent(node.path),
                depth: node.depth,
                description: node.description ?? null,
                count: node.id != null ? (counts[node.id]?.count ?? 0) : 0,
                total: totals.get(node.path) ?? 0,
            });

            walk(node.children ?? []);
        }
    };

    walk(tree);

    return rows;
}
