import { useCallback, useEffect, useState } from "react";
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Box,
    Button,
    CircularProgress,
    IconButton,
    MenuItem,
    Select,
    Switch,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TextField,
    Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import CloudDownloadIcon from "@mui/icons-material/CloudDownload";
import { api } from "../api/client";
import SectionPage from "../components/SectionPage";
import type { components } from "../api/generated/schema";

interface ConfigNode {
    value?: unknown;
    description?: string;
    children?: Record<string, ConfigNode>;
}

type PackageInfo = components["schemas"]["PackageInfo"];

const ABOUT_SECTION = "About";

function formatLabel(name: string): string {
    return name.replace(/_/g, " ").replace(/^\w/, (char) => char.toUpperCase());
}

const YOLO_MODELS: Record<string, string> = {
    "yolo26n.pt": "Nano",
    "yolo26s.pt": "Small",
    "yolo26m.pt": "Medium",
    "yolo26l.pt": "Large",
    "yolo26x.pt": "Extra Large",
};

function ModelChooser({
    value,
    path,
    onUpdate,
}: {
    value: string;
    path: string[];
    onUpdate: (path: string[], value: unknown) => void;
}) {
    const [downloaded, setDownloaded] = useState<string[]>([]);
    const [downloading, setDownloading] = useState<string | null>(null);

    const fetchModels = useCallback(() => {
        api.GET("/api/models").then(({ data }) => {
            if (data) {
                setDownloaded(data);
            }
        });
    }, []);

    useEffect(() => {
        fetchModels();
    }, [fetchModels]);

    const handleDownload = useCallback(
        async (modelName: string) => {
            setDownloading(modelName);

            try {
                await api.POST("/api/models/{name}/download", { params: { path: { name: modelName } } });
                fetchModels();
            } finally {
                setDownloading(null);
            }
        },
        [fetchModels],
    );

    return (
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <Typography sx={{ fontSize: 14, minWidth: 120 }}>Model</Typography>
            <Select
                size="small"
                fullWidth
                value={value}
                onChange={(e) => onUpdate(path, e.target.value)}
                sx={{ fontSize: 14 }}
            >
                {Object.entries(YOLO_MODELS).map(([file, label]) => (
                    <MenuItem key={file} value={file} sx={{ fontSize: 14 }}>
                        <Box sx={{ display: "flex", alignItems: "center", gap: 1, width: "100%" }}>
                            <span>{label} ({file})</span>
                            <Box sx={{ flex: 1 }} />
                            {downloading === file ? (
                                <CircularProgress size={16} />
                            ) : !downloaded.includes(file) ? (
                                <IconButton
                                    size="small"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleDownload(file);
                                    }}
                                >
                                    <CloudDownloadIcon fontSize="small" />
                                </IconButton>
                            ) : null}
                        </Box>
                    </MenuItem>
                ))}
            </Select>
        </Box>
    );
}

function cloneTree(node: ConfigNode): ConfigNode {
    const children = node.children
        ? Object.fromEntries(Object.entries(node.children).map(([k, v]) => [k, cloneTree(v)]))
        : undefined;
    return { ...node, children };
}

function updateValue(tree: ConfigNode, path: string[], value: unknown): ConfigNode {
    tree = cloneTree(tree);

    let current = tree;

    for (let i = 0; i < path.length - 1; i++) {
        if (!current.children) {
            current.children = {};
        }

        if (!current.children[path[i]]) {
            current.children[path[i]] = {};
        }

        current = current.children[path[i]];
    }

    const last = path[path.length - 1];

    if (!current.children) {
        current.children = {};
    }

    current.children[last] = { ...current.children[last], value };

    return tree;
}

function parseValue(raw: string, original: unknown): unknown {
    if (typeof original === "boolean") {
        return raw === "true";
    }

    if (typeof original === "number") {
        const n = Number(raw);
        return isNaN(n) ? original : n;
    }

    return raw;
}

function ConfigLeafField({
    name,
    node,
    path,
    onUpdate,
}: {
    name: string;
    node: ConfigNode;
    path: string[];
    onUpdate: (path: string[], value: unknown) => void;
}) {
    if (name === "model" && path.length >= 2 && path[path.length - 2] === "Object" && typeof node.value === "string") {
        return <ModelChooser value={node.value} path={path} onUpdate={onUpdate} />;
    }

    if (typeof node.value === "boolean") {
        return (
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                <Typography sx={{ fontSize: 14, flex: 1 }}>{formatLabel(name)}</Typography>
                {node.description && (
                    <Typography sx={{ fontSize: 12, color: "text.secondary" }}>{node.description}</Typography>
                )}
                <Switch
                    size="small"
                    checked={node.value}
                    onChange={(e) => onUpdate(path, e.target.checked)}
                />
            </Box>
        );
    }

    return (
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <Typography sx={{ fontSize: 14, minWidth: 120 }}>{formatLabel(name)}</Typography>
            {node.description && (
                <Typography sx={{ fontSize: 12, color: "text.secondary", flex: 1 }}>{node.description}</Typography>
            )}
            <TextField
                size="small"
                sx={{ minWidth: 200 }}
                defaultValue={node.value === null || node.value === undefined ? "" : String(node.value)}
                onBlur={(e) => onUpdate(path, parseValue(e.target.value, node.value))}
                slotProps={{ input: { sx: { fontSize: 14 } } }}
            />
        </Box>
    );
}

function ConfigChildRow({
    name,
    node,
    path,
    onUpdate,
}: {
    name: string;
    node: ConfigNode;
    path: string[];
    onUpdate: (path: string[], value: unknown) => void;
}) {
    const children = node.children ?? {};
    const childrenCount = Object.keys(children).length;

    if (childrenCount > 0) {
        return (
            <Accordion disableGutters>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 1, width: "100%" }}>
                        <Typography sx={{ fontSize: 14, fontWeight: 500 }}>{formatLabel(name)}</Typography>
                        {node.description && (
                            <Typography sx={{ fontSize: 12, color: "text.secondary" }}>{node.description}</Typography>
                        )}
                    </Box>
                </AccordionSummary>
                <AccordionDetails sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
                    {Object.entries(children).map(([childName, childNode]) => (
                        <ConfigChildRow
                            key={childName}
                            name={childName}
                            node={childNode}
                            path={[...path, childName]}
                            onUpdate={onUpdate}
                        />
                    ))}
                </AccordionDetails>
            </Accordion>
        );
    }

    return (
        <Box
            sx={{
                px: 1.5,
                py: 0.5,
                border: 1,
                borderColor: "divider",
                borderRadius: 1,
                bgcolor: "action.hover",
            }}
        >
            <ConfigLeafField name={name} node={node} path={path} onUpdate={onUpdate} />
        </Box>
    );
}

function AboutPane() {
    const [packages, setPackages] = useState<PackageInfo[] | null>(null);

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/about/packages")
            .then(({ data, error }) => {
                if (!cancelled && !error && data) {
                    setPackages(data);
                }
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, []);

    if (packages === null) {
        return null;
    }

    return (
        <TableContainer>
            <Table size="small">
                <TableHead>
                    <TableRow>
                        <TableCell>Name</TableCell>
                        <TableCell>Version</TableCell>
                        <TableCell>License</TableCell>
                    </TableRow>
                </TableHead>
                <TableBody>
                    {packages.map((packageInfo) => (
                        <TableRow key={packageInfo.name}>
                            <TableCell>{packageInfo.name}</TableCell>
                            <TableCell>{packageInfo.version}</TableCell>
                            <TableCell>{packageInfo.license || "-"}</TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </TableContainer>
    );
}

export default function ConfigurationPage() {
    const [config, setConfig] = useState<ConfigNode | null>(null);
    const [edited, setEdited] = useState<ConfigNode | null>(null);
    const [selected, setSelected] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/configuration")
            .then(({ data }) => {
                if (!cancelled && data) {
                    const tree = data as ConfigNode;
                    setConfig(tree);
                    setEdited(cloneTree(tree));
                }
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, []);

    const handleSelect = useCallback((id: string) => {
        setSelected(id);
    }, []);

    const handleUpdate = useCallback(
        (path: string[], value: unknown) => {
            setEdited((prev) => (prev ? updateValue(prev, path, value) : prev));
        },
        [],
    );

    const handleSave = useCallback(async () => {
        if (!edited) return;

        setSaving(true);

        try {
            const { error } = await api.POST("/api/configuration", { body: edited as Record<string, unknown> });

            if (!error) {
                setConfig(cloneTree(edited));
            }
        } finally {
            setSaving(false);
        }
    }, [edited]);

    const handleReset = useCallback(() => {
        if (config) {
            setEdited(cloneTree(config));
        }
    }, [config]);

    const rootChildren = edited?.children ?? {};
    const sections = [
        ...Object.keys(rootChildren).map((name) => ({ id: name, label: formatLabel(name) })),
        { id: ABOUT_SECTION, label: ABOUT_SECTION },
    ];
    const selectedNode = selected ? rootChildren[selected] : undefined;
    const isAbout = selected === ABOUT_SECTION;
    const isDirty = JSON.stringify(edited) !== JSON.stringify(config);

    return (
        <SectionPage title="Configuration" sections={sections} selected={selected ?? ""} onSelect={handleSelect}>
            {isAbout ? (
                <AboutPane />
            ) : selectedNode ? (
                <>
                    <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 2 }}>
                        <Box sx={{ display: "flex", flexDirection: "column", gap: 0.5, flex: 1 }}>
                            <Typography variant="h6">
                                {selectedNode.description ?? formatLabel(selected!)}
                            </Typography>
                        </Box>
                        <Box sx={{ display: "flex", gap: 1, flexShrink: 0 }}>
                            <Button size="small" disabled={!isDirty || saving} onClick={handleReset}>
                                Reset
                            </Button>
                            <Button size="small" variant="contained" disabled={!isDirty || saving} onClick={handleSave}>
                                Save
                            </Button>
                        </Box>
                    </Box>
                    <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
                        {Object.entries(selectedNode.children ?? {}).map(([name, node]) => (
                            <ConfigChildRow
                                key={name}
                                name={name}
                                node={node}
                                path={[selected!, name]}
                                onUpdate={handleUpdate}
                            />
                        ))}
                    </Box>
                </>
            ) : (
                <Typography color="text.secondary">Select a section on the left.</Typography>
            )}
        </SectionPage>
    );
}
