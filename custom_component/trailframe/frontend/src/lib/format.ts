const formatter = new Intl.DateTimeFormat("sv-SE", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
});

export function formatDateTime(iso: string | null | undefined): string {
    if (!iso) {
        return "";
    }

    const date = new Date(iso);
    return formatter.format(date);
}
