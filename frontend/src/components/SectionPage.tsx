import { Box, IconButton, List, ListItemButton, ListItemText, Typography } from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { useState } from "react";
import type { ReactNode } from "react";

export interface Section {
    id: string;
    label: string;
}

interface SectionPageProps {
    title: string;
    sections: Section[];
    selected: string;
    onSelect: (id: string) => void;
    children: ReactNode;
}

export default function SectionPage({ title, sections, selected, onSelect, children }: SectionPageProps) {
    const [collapsed, setCollapsed] = useState(false);

    return (
        <Box sx={{ flex: 1, minHeight: 0, display: "flex" }}>
            <Box
                sx={{
                    display: "flex",
                    flexDirection: "column",
                    width: collapsed ? 40 : 320,
                    flexShrink: 0,
                    borderRight: 1,
                    borderColor: "divider",
                    overflowY: "auto",
                    overflowX: "hidden",
                    transition: "width 0.2s",
                }}
            >
                <Box sx={{ display: "flex", justifyContent: "center", py: 0.5 }}>
                    <IconButton
                        size="small"
                        onClick={() => setCollapsed(!collapsed)}
                        aria-label={collapsed ? `Expand ${title} menu` : `Collapse ${title} menu`}
                    >
                        {collapsed ? <ChevronRightIcon /> : <ChevronLeftIcon />}
                    </IconButton>
                </Box>
                {!collapsed && (
                    <>
                        <Typography variant="subtitle2" sx={{ px: 2, mb: 0.5 }}>
                            {title}
                        </Typography>
                        <List dense disablePadding>
                            {sections.map(({ id, label }) => (
                                <ListItemButton
                                    key={id}
                                    selected={selected === id}
                                    onClick={() => onSelect(id)}
                                    sx={{ mx: 1, borderRadius: 1 }}
                                >
                                    <ListItemText primary={label} />
                                </ListItemButton>
                            ))}
                        </List>
                    </>
                )}
            </Box>
            <Box sx={{ flex: 1, minWidth: 0, overflowY: "auto", p: 2, textAlign: "left", display: "flex", flexDirection: "column" }}>
                {children}
            </Box>
        </Box>
    );
}
