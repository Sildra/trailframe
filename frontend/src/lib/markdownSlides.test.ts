import { describe, expect, it } from "vitest";
import { splitSlides } from "./markdownSlides";

describe("splitSlides", () => {
    it("splits on a line containing only three dashes", () => {
        expect(splitSlides("# First\n\nOne\n\n---\n\n# Second\n\nTwo")).toEqual([
            "# First\n\nOne",
            "# Second\n\nTwo",
        ]);
    });

    it("handles CRLF input", () => {
        expect(splitSlides("First\r\n\r\n---\r\n\r\nSecond")).toEqual(["First", "Second"]);
    });

    it("keeps separators inside fenced code blocks", () => {
        expect(splitSlides("Before\n\n```\n---\n```\n\nAfter")).toEqual(["Before\n\n```\n---\n```\n\nAfter"]);
    });

    it("does not close a fenced block on an info string", () => {
        expect(splitSlides("Before\n\n```python\n---\n```\n\nAfter")).toEqual(["Before\n\n```python\n---\n```\n\nAfter"]);
    });

    it("ignores empty slides and trailing separators", () => {
        expect(splitSlides("---\n\nFirst\n\n---\n\n---\n")).toEqual(["First"]);
    });

    it("returns one slide when there is no separator", () => {
        expect(splitSlides("Just one slide")).toEqual(["Just one slide"]);
    });

    it("returns no slides for an empty document", () => {
        expect(splitSlides("")).toEqual([]);
    });
});
