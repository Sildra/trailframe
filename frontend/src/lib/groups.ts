import type { components } from "../api/generated/schema";

type PhotoGroupSummary = components["schemas"]["PhotoGroupSummary"];

export function groupKey(group: PhotoGroupSummary): string {
    return group.automatic ? `auto:${group.name}` : `user:${group.id}`;
}

export function duplicateKey(group: PhotoGroupSummary): string {
    return `dup:${[...(group.photo_ids ?? [])].sort((a, b) => a - b).join(",")}`;
}

export function locationIssueKey(group: PhotoGroupSummary): string {
    return `loc:${group.name}`;
}
