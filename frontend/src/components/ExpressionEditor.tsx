import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Box, Chip, Tooltip, Typography, useTheme } from "@mui/material";
import { hintsFor, tokenize, type Hint, type ParseIssue, type RuleSchema, type Token } from "../lib/expression";
import { ensureUnit, typeCharacter } from "../lib/expression/typing";

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
    unit: "#ffcb6b",
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
    unit: "#a16207",
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

const EMPTY_VALUES: Record<string, string[]> = {};

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
    /** The served rule schema, used for the contextual hints. */
    schema?: RuleSchema | null;
    /** The served value dictionaries, used for the value hints. */
    values?: Record<string, string[]>;
}

/** A local, syntax-coloured multiline editor; it never calls the backend. */
export default function ExpressionEditor({
    value,
    onChange,
    issue,
    onCompositionChange,
    schema = null,
    values = EMPTY_VALUES,
}: ExpressionEditorProps) {
    const theme = useTheme();
    const area = useRef<HTMLTextAreaElement | null>(null);
    const composing = useRef(false);
    /** Unit filling is armed by an operator hint and disarmed once it fired. */
    const unitFill = useRef(false);
    const [caret, setCaret] = useState(value.length);
    const [focused, setFocused] = useState(false);
    const colors = theme.palette.mode === "dark" ? DARK_COLORS : LIGHT_COLORS;
    const nodes = useMemo(() => segments(value, colors), [value, colors]);
    const hints = useMemo(
        () => (schema ? hintsFor(schema, values, value, Math.min(caret, value.length)) : null),
        [schema, values, value, caret],
    );

    // Grow with the content: a scrollbar would narrow the textarea and desync the overlay.
    useLayoutEffect(() => fitHeight(area.current), [value]);

    useEffect(() => {
        const handleResize = () => fitHeight(area.current);

        window.addEventListener("resize", handleResize);

        return () => window.removeEventListener("resize", handleResize);
    }, []);

    const applyEdit = (next: string, position: number) => {
        onChange(next);
        setCaret(position);

        requestAnimationFrame(() => {
            const element = area.current;

            if (element !== null) {
                element.focus();
                element.setSelectionRange(position, position);
            }
        });
    };

    const applyHint = (hint: Hint) => {
        if (hints === null) {
            return;
        }

        // Hints after a step keyword are appended, so `objects has` becomes
        // `objects has "dog"` rather than `objects has"dog"`.
        const prefix = hints.start === hints.end && hints.start > 0 && !/\s/.test(value[hints.start - 1]) ? " " : "";
        const offset = prefix.length + (hint.caret ?? hint.insert.length);

        // Only an operator pick arms unit filling: the next number typed in that
        // slot then gets its unit, while ordinary typing never inserts one.
        unitFill.current = hint.kind === "operator";
        applyEdit(value.slice(0, hints.start) + prefix + hint.insert + value.slice(hints.end), hints.start + offset);
    };

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
                    onChange={(event) => {
                        const next = event.target.value;
                        let position = event.target.selectionStart ?? next.length;
                        let text = next;

                        if (schema && !composing.current && unitFill.current) {
                            const filled = ensureUnit(schema, next, position);

                            if (filled) {
                                text = filled.text;
                                position = filled.caret;
                                unitFill.current = false;
                            }
                        }

                        onChange(text);
                        setCaret(position);
                    }}
                    onSelect={(event) => setCaret(event.currentTarget.selectionStart)}
                    onFocus={() => setFocused(true)}
                    onBlur={() => {
                        unitFill.current = false;
                        setFocused(false);
                    }}
                    onKeyDown={(event) => {
                        if (event.key === "Tab" && hints !== null && hints.hints.length > 0) {
                            event.preventDefault();
                            applyHint(hints.hints[0]);
                            return;
                        }

                        if (schema === null || composing.current || event.ctrlKey || event.metaKey || event.altKey) {
                            return;
                        }

                        if (event.key.length !== 1) {
                            return;
                        }

                        const position = event.currentTarget.selectionStart ?? 0;
                        const edited = typeCharacter(schema, event.currentTarget.value, position, event.key);

                        if (edited) {
                            event.preventDefault();
                            applyEdit(edited.text, edited.caret);
                        }
                    }}
                    onCompositionStart={() => {
                        composing.current = true;
                        onCompositionChange?.(true);
                    }}
                    onCompositionEnd={(event) => {
                        composing.current = false;
                        onCompositionChange?.(false);
                        onChange(event.currentTarget.value);
                    }}
                    spellCheck={false}
                    autoCapitalize="off"
                    autoCorrect="off"
                    placeholder='objects has "dog" with confidence >= 80% and is_favorite is true'
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

            {focused && hints !== null && (hints.hints.length > 0 || hints.note) && (
                <Box
                    sx={{
                        display: "flex",
                        alignItems: "center",
                        gap: 0.5,
                        flexWrap: "wrap",
                        mt: 0.75,
                    }}
                >
                    <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>
                        {hints.title}
                    </Typography>
                    {hints.hints.map((hint) => (
                        <Tooltip key={`${hint.kind}:${hint.insert}`} title={hint.detail} arrow>
                            <Chip
                                label={hint.label}
                                size="small"
                                variant="outlined"
                                onClick={() => applyHint(hint)}
                                onMouseDown={(event) => event.preventDefault()}
                                sx={{ fontFamily: MONO.fontFamily, fontSize: 12 }}
                            />
                        </Tooltip>
                    ))}
                    {hints.hints.length === 0 && hints.note && (
                        <Typography variant="caption" color="text.secondary" sx={{ fontStyle: "italic" }}>
                            {hints.note}
                        </Typography>
                    )}
                </Box>
            )}

            {issue && (
                <Typography variant="caption" color="error.main" sx={{ display: "block", mt: 0.5 }}>
                    {issue.message}
                </Typography>
            )}
        </Box>
    );
}
