/**
 * Split a Markdown document into slides.
 *
 * A separator is a line containing only three or more dashes. Separators inside
 * fenced code blocks belong to the code and are kept as content.
 */
export function splitSlides(markdown: string): string[] {
    const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
    const slides: string[] = [];
    let current: string[] = [];
    let fence: string | null = null;

    const flush = () => {
        const slide = current.join("\n").trim();
        if (slide.length > 0) {
            slides.push(slide);
        }
        current = [];
    };

    for (const line of lines) {
        const fenceMatch = line.match(/^\s{0,3}(`{3,}|~{3,})(.*)$/);

        if (fenceMatch) {
            const marker = fenceMatch[1][0];

            if (fence === null) {
                fence = marker;
            } else if (marker === fence && fenceMatch[2].trim() === "") {
                fence = null;
            }

            current.push(line);
            continue;
        }

        if (fence === null && /^\s{0,3}-{3,}\s*$/.test(line)) {
            flush();
            continue;
        }

        current.push(line);
    }

    flush();

    return slides;
}
