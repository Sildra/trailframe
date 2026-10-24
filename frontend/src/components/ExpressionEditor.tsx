import { useMemo, useRef } from "react";
import { Box, Typography } from "@mui/material";
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

const COLORS: Record<string, string> = {
    keyword: "#c792ea",
    field: "#82aaff",
    string: "#c3e88d",
    number: "#f78c6c",
    date: "#ffcb6b",
    operator: "#89ddff",
    punct: "#89ddff",
    unknown: "#ff5370",
};

function tokenColor(token: Token): string {
    if (token.kind === "word") {
        return KEYWORDS.has(token.text.toLowerCase()) ? COLORS.keyword : COLORS.field;
    }

    return COLORS[token.kind] ?? COLORS.operator;
}

function segments(value: string) {
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

        nodes.push({ text: value.slice(token.start, token.end), color: tokenColor(token), key: index * 2 + 1 });
        cursor = token.end;
    });

    if (cursor < value.length) {
        nodes.push({ text: value.slice(cursor), key: tokens.length * 2 });
    }

    return nodes;
}

export interface ExpressionEditorProps {
    value: string;
    onChange: (value: string) => void;
    issue?: ParseIssue | null;
    onCompositionChange?: (composing: boolean) => void;
}

/** A local, syntax-coloured multiline editor; it never calls the backend. */
export default function ExpressionEditor({ value, onChange, issue, onCompositionChange }: ExpressionEditorProps) {
    const overlay = useRef<HTMLPreElement | null>(null);
    const nodes = useMemo(() => segments(value), [value]);

    return (
        <Box>
            <Box
                sx={{
                    position: "relative",
                    border: 1,
                    borderColor: issue ? "error.main" : "divider",
                    borderRadius: 1,
                    bgcolor: "action.hover",
                    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                    fontSize: 14,
                    lineHeight: 1.6,
                }}
            >
                <Box
                    component="pre"
                    ref={overlay}
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
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    onCompositionStart={() => onCompositionChange?.(true)}
                    onCompositionEnd={(event) => {
                        onCompositionChange?.(false);
                        onChange(event.currentTarget.value);
                    }}
                    onScroll={(event) => {
                        if (overlay.current) {
                            overlay.current.scrollTop = event.currentTarget.scrollTop;
                            overlay.current.scrollLeft = event.currentTarget.scrollLeft;
                        }
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
                        minHeight: 116,
                        resize: "vertical",
                        border: 0,
                        outline: 0,
                        px: 1.5,
                        py: 1.25,
                        bgcolor: "transparent",
                        color: "transparent",
                        caretColor: "text.primary",
                        font: "inherit",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        overflow: "auto",
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
