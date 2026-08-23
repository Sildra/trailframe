import type { components } from "../api/generated/schema";

type PhotoGroupSummary = components["schemas"]["PhotoGroupSummary"];

export function groupKey(group: PhotoGroupSummary): string {
    return group.automatic ? `auto:${group.name}` : `user:${group.id}`;
}
