import { useMemo, useState } from "react";
import { Box, Checkbox, Collapse, IconButton, List, ListItemButton, ListItemText, Typography } from "@mui/material";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import type { TagNode } from "../lib/tags";

interface TagBranchProps {
    node: TagNode;
    depth: number;
    expanded: Set<string>;
    selectedPath: string | null;
    checkedPaths: string[];
    checkable: boolean;
    autoExpand: boolean;
    onSelect: (node: TagNode) => void;
    onToggleExpand: (path: string) => void;
    onToggleCheck: (path: string, checked: boolean) => void;
}

function TagBranch({
    node,
    depth,
    expanded,
    selectedPath,
    checkedPaths,
    checkable,
    autoExpand,
    onSelect,
    onToggleExpand,
    onToggleCheck,
}: TagBranchProps) {
    const children = node.children ?? [];
    const hasChildren = children.length > 0;
    const isExpanded = autoExpand || expanded.has(node.path);
    const isChecked = checkedPaths.includes(node.path);

    return (
        <>
            <ListItemButton
                dense
                selected={selectedPath === node.path}
                onClick={() => onSelect(node)}
                sx={{ pl: 0.5 + depth * 1.75, pr: 0.5, py: 0.1, borderRadius: 1 }}
            >
                {hasChildren ? (
                    <IconButton
                        size="small"
                        edge="start"
                        aria-label={isExpanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
                        onClick={(event) => {
                            event.stopPropagation();
                            onToggleExpand(node.path);
                        }}
                    >
                        {isExpanded ? <ExpandMoreIcon fontSize="small" /> : <ChevronRightIcon fontSize="small" />}
                    </IconButton>
                ) : (
                    <Box sx={{ width: 30, flexShrink: 0 }} />
                )}
                {checkable && (
                    <Checkbox
                        size="small"
                        checked={isChecked}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => onToggleCheck(node.path, event.target.checked)}
                        slotProps={{ input: { "aria-label": node.path } }}
                    />
                )}
                <ListItemText
                    primary={node.name}
                    secondary={node.description ?? undefined}
                    slotProps={{
                        primary: { sx: { fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } },
                        secondary: { sx: { fontSize: 11, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } },
                    }}
                />
                {node.total > 0 && (
                    <Typography variant="caption" color="text.secondary" sx={{ pl: 0.5, flexShrink: 0 }}>
                        {node.total}
                    </Typography>
                )}
            </ListItemButton>
            {hasChildren && (
                <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                    <List disablePadding>
                        {children.map((child) => (
                            <TagBranch
                                key={child.path}
                                node={child}
                                depth={depth + 1}
                                expanded={expanded}
                                selectedPath={selectedPath}
                                checkedPaths={checkedPaths}
                                checkable={checkable}
                                autoExpand={autoExpand}
                                onSelect={onSelect}
                                onToggleExpand={onToggleExpand}
                                onToggleCheck={onToggleCheck}
                            />
                        ))}
                    </List>
                </Collapse>
            )}
        </>
    );
}

export interface TagTreeProps {
    nodes: TagNode[];
    /** Path of the selected node. */
    selectedPath?: string | null;
    onSelect?: (node: TagNode) => void;
    /** Paths of the checked nodes. */
    checkedPaths?: string[];
    /** Show a checkbox in front of every node. */
    checkable?: boolean;
    onToggleCheck?: (path: string, checked: boolean) => void;
    /** Only the nodes matching this text (and their ancestors) are shown. */
    filter?: string;
    emptyLabel?: string;
}

function filterTree(nodes: TagNode[], filter: string): TagNode[] {
    const needle = filter.trim().toLowerCase();

    if (!needle) {
        return nodes;
    }

    const keep = (node: TagNode): TagNode | null => {
        const children = (node.children ?? []).map(keep).filter((child): child is TagNode => child !== null);
        const matches = node.path.toLowerCase().includes(needle);

        if (!matches && children.length === 0) {
            return null;
        }

        return { ...node, children };
    };

    return nodes.map(keep).filter((node): node is TagNode => node !== null);
}

export default function TagTree({
    nodes,
    selectedPath = null,
    onSelect,
    checkedPaths,
    checkable = false,
    onToggleCheck,
    filter = "",
    emptyLabel = "No tags yet.",
}: TagTreeProps) {
    const [expanded, setExpanded] = useState<Set<string>>(new Set());

    const visible = useMemo(() => filterTree(nodes, filter), [nodes, filter]);
    const autoExpand = filter.trim().length > 0;

    const toggleExpand = (path: string) => {
        setExpanded((previous) => {
            const next = new Set(previous);

            if (next.has(path)) {
                next.delete(path);
            } else {
                next.add(path);
            }

            return next;
        });
    };

    const toggleCheck = (path: string, checked: boolean) => {
        if (!onToggleCheck) {
            return;
        }

        onToggleCheck(path, checked);
    };

    if (nodes.length === 0) {
        return (
            <Typography variant="body2" color="text.secondary" sx={{ px: 1, py: 1 }}>
                {emptyLabel}
            </Typography>
        );
    }

    return (
        <List dense disablePadding sx={{ width: "100%" }}>
            {visible.map((node) => (
                <TagBranch
                    key={node.path}
                    node={node}
                    depth={0}
                    expanded={expanded}
                    selectedPath={selectedPath}
                    checkedPaths={checkedPaths ?? []}
                    checkable={checkable}
                    autoExpand={autoExpand}
                    onSelect={(target) => onSelect?.(target)}
                    onToggleExpand={toggleExpand}
                    onToggleCheck={toggleCheck}
                />
            ))}
        </List>
    );
}
