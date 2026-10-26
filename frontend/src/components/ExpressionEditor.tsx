import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { Box, Typography, useTheme } from "@mui/material";
import { tokenize, type ParseIssue, type Token } from "../lib/expression";

const KEYWORDS = new Set([
    "and",
    "or",
    "has",
    "no",
    "with",
    "is",
    "not",
    "true",
    "false",
    "contains",
    "in",
    "objects",
]);

/** Shared by the overlay and the textarea so glyphs and caret stay on the same grid. */
const MONO = {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    fontSize: 14,
    lineHeight: 1.6,
    letterSpacing: 0,
} as const;

const DARK_COLORS: Record<string, string> = {
    keyword: "#c792ea",
    field: "#82aaff",
    string: "#c3e88d",
    number: "#f78c6c",
    date: "#ffcb6b",
    operator: "#89ddff",
    punct: "#89ddff",
    unknown: "#ff5370",
};

const LIGHT_COLORS: Record<string, string> = {
    keyword: "#7c3aed",
    field: "#1d4ed8",
    string: "#15803d",
    number: "#c2410c",
    date: "#a16207",
    operator: "#0e7490",
    punct: "#0e7490",
    unknown: "#dc2626",
};

function tokenColor(token: Token, colors: Record<string, string>): string {
    if (token.kind === "word") {
        return KEYWORDS.has(token.text.toLowerCase()) ? colors.keyword : colors.field;
    }

    return colors[token.kind] ?? colors.operator;
}

const MIN_HEIGHT = 116;

function segments(value: string, colors: Record<string, string>) {
    const { tokens } = tokenize(value);
    const nodes: { text: string; color?: string; key: number }[] = [];
    let cursor = 0;

    tokens.forEach((token, index) => {
        if (token.kind === "eof") {
            return;
        }

        if (token.start > cursor) {
            nodes.push({ text: value.slice(cursor, token.start), key: index * 2 });
        }

        nodes.push({ text: value.slice(token.start, token.end), color: tokenColor(token, colors), key: index * 2 + 1 });
        cursor = token.end;
    });

    if (cursor < value.length) {
        nodes.push({ text: value.slice(cursor), key: tokens.length * 2 });
    }

    return nodes;
}

function fitHeight(element: HTMLTextAreaElement | null) {
    if (element === null) {
        return;
    }

    element.style.height = "auto";
    element.style.height = `${Math.max(element.scrollHeight, MIN_HEIGHT)}px`;
}

export interface ExpressionEditorProps {
    value: string;
    onChange: (value: string) => void;
    issue?: ParseIssue | null;
    onCompositionChange?: (composing: boolean) => void;
}

/** A local, syntax-coloured multiline editor; it never calls the backend. */
export default function ExpressionEditor({ value, onChange, issue, onCompositionChange }: ExpressionEditorProps) {
    const theme = useTheme();
    const area = useRef<HTMLTextAreaElement | null>(null);
    const colors = theme.palette.mode === "dark" ? DARK_COLORS : LIGHT_COLORS;
    const nodes = useMemo(() => segments(value, colors), [value, colors]);

    // Grow with the content: a scrollbar would narrow the textarea and desync the overlay.
    useLayoutEffect(() => fitHeight(area.current), [value]);

    useEffect(() => {
        const handleResize = () => fitHeight(area.current);

        window.addEventListener("resize", handleResize);

        return () => window.removeEventListener("resize", handleResize);
    }, []);

    return (
        <Box>
            <Box
                sx={{
                    position: "relative",
                    border: 1,
                    borderColor: issue ? "error.main" : "divider",
                    borderRadius: 1,
                    bgcolor: "action.hover",
                    ...MONO,
                }}
            >
                <Box
                    component="pre"
                    aria-hidden
                    sx={{
                        position: "absolute",
                        inset: 0,
                        m: 0,
                        px: 1.5,
                        py: 1.25,
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        overflow: "hidden",
                        pointerEvents: "none",
                        color: "text.primary",
                        ...MONO,
                    }}
                >
                    {nodes.map((node) => (
                        <span key={node.key} style={{ color: node.color }}>
                            {node.text}
                        </span>
                    ))}
                    {"\n"}
                </Box>

                <Box
                    component="textarea"
                    ref={area}
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    onCompositionStart={() => onCompositionChange?.(true)}
                    onCompositionEnd={(event) => {
                        onCompositionChange?.(false);
                        onChange(event.currentTarget.value);
                    }}
                    spellCheck={false}
                    autoCapitalize="off"
                    autoCorrect="off"
                    placeholder='objects has "dog" with confidence >= 0.8 and is_favorite is true'
                    aria-label="Rule expression"
                    sx={{
                        position: "relative",
                        display: "block",
                        width: "100%",
                        minHeight: MIN_HEIGHT,
                        resize: "none",
                        border: 0,
                        outline: 0,
                        px: 1.5,
                        py: 1.25,
                        bgcolor: "transparent",
                        color: "transparent",
                        caretColor: (theme) => theme.palette.text.primary,
                        ...MONO,
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        overflow: "hidden",
                        "&::placeholder": { color: "text.disabled", opacity: 1 },
                        "&::selection": { backgroundColor: "primary.main", color: "transparent" },
                    }}
                />
            </Box>

            {issue && (
                <Typography variant="caption" color="error.main" sx={{ display: "block", mt: 0.5 }}>
                    {issue.message}
                </Typography>
            )}
        </Box>
    );
}
