import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Box,
    Button,
    Chip,
    CircularProgress,
    Collapse,
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
import AddIcon from "@mui/icons-material/Add";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import DeleteIcon from "@mui/icons-material/Delete";
import { api } from "../api/client";
import SectionPage from "../components/SectionPage";
import type { components } from "../api/generated/schema";

interface ConfigNode {
    value?: unknown;
    description?: string;
    children?: Record<string, ConfigNode>;
    item?: {
        kind?: string;
        scalar_type?: string;
        keys?: Record<string, string>;
        template?: unknown;
        fields?: Record<string, FieldDescriptor>;
    };
}

type ScannerDefinition = {
    name: string;
    can_be_disabled: boolean;
    can_be_remote: boolean;
};

interface FieldDescriptor {
    editor?: string;
    options?: ScannerDefinition[];
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

const CONTROL_HEIGHT = 30;

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
                sx={{
                    fontSize: 14,
                    height: CONTROL_HEIGHT,
                    "& .MuiOutlinedInput-input": { padding: "0 14px", lineHeight: "20px" },
                }}
                slotProps={{ input: { sx: { fontSize: 14 } } }}
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

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

function removeIndex<T>(list: T[], index: number): T[] {
    return list.filter((_, i) => i !== index);
}

function moveIndex<T>(list: T[], from: number, to: number): T[] {
    if (to < 0 || to >= list.length || from === to) {
        return list;
    }

    const next = [...list];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    return next;
}

function setRecordField(record: Record<string, unknown>, field: string, value: unknown): Record<string, unknown> {
    return { ...record, [field]: value };
}

function renameRecordKey(record: Record<string, unknown>, nextName: string): Record<string, unknown> {
    const [key] = Object.keys(record);
    const settings = record[key];
    const next: Record<string, unknown> = { ...record };
    delete next[key];
    next[nextName] = settings;
    return next;
}

function setNestedField(record: Record<string, unknown>, key: string, field: string, value: unknown): Record<string, unknown> {
    return { ...record, [key]: { ...(isRecord(record[key]) ? record[key] : {}), [field]: value } };
}

function parseScalarValue(raw: string, scalarType: string | undefined): unknown {
    if (scalarType === "number") {
        const n = Number(raw);
        return isNaN(n) ? raw : n;
    }

    if (scalarType === "bool") {
        return raw === "true";
    }

    return raw;
}

function cloneTemplate(descriptor: ConfigNode["item"] | undefined): unknown {
    const template = descriptor?.template;

    if (template !== undefined) {
        return JSON.parse(JSON.stringify(template));
    }

    return "";
}

function updateListNode(
    tree: ConfigNode,
    nodePath: string[],
    op: (list: unknown[]) => unknown[],
): ConfigNode {
    tree = cloneTree(tree);

    let node: ConfigNode = tree;

    for (const key of nodePath) {
        if (!node.children) {
            node.children = {};
        }

        if (!node.children[key]) {
            node.children[key] = {};
        }

        node = node.children[key];
    }

    node.value = op(Array.isArray(node.value) ? node.value : []);
    return tree;
}

function Chooser({
    value,
    remote,
    options,
    onAdd,
}: {
    value: string[];
    remote: boolean;
    options: ScannerDefinition[];
    onAdd: (name: string) => void;
}) {
    const selectable = options.filter(
        (definition) =>
            (remote ? definition.can_be_remote : definition.can_be_disabled) && !value.includes(definition.name),
    );

    return (
        <Select
            size="small"
            fullWidth
            displayEmpty
            value=""
            onChange={(e) => {
                if (e.target.value) {
                    onAdd(e.target.value as string);
                }
            }}
            sx={{
                fontSize: 14,
                height: CONTROL_HEIGHT,
                "& .MuiOutlinedInput-input": { padding: "0 14px", lineHeight: "20px" },
            }}
        >
            <MenuItem value="" sx={{ fontSize: 14, color: "text.secondary", justifyContent: "flex-start" }}>
                <Box component="span">Add scanner…</Box>
                <Box component="span" sx={{ flex: 1 }} />
            </MenuItem>
            {selectable.length > 0
                ? selectable.map((definition) => (
                      <MenuItem key={definition.name} value={definition.name} sx={{ fontSize: 14 }}>
                          {definition.name}
                          <Box component="span" sx={{ flex: 1 }} />
                          <Typography
                              component="span"
                              sx={{ fontSize: 12, color: "text.secondary", ml: 0.75, whiteSpace: "nowrap" }}
                          >
                              {remote ? (definition.can_be_remote ? "remote" : "local only") : "local"}
                          </Typography>
                      </MenuItem>
                  ))
                : null}
        </Select>
    );
}

function FieldRow({
    field,
    value,
    remote,
    descriptor,
    onField,
}: {
    field: string;
    value: unknown;
    remote: boolean;
    descriptor?: FieldDescriptor;
    onField: (next: unknown) => void;
}) {
    const label = <Typography sx={{ fontSize: 14, minWidth: 110 }}>{formatLabel(field)}</Typography>;

    if (typeof value === "boolean") {
        return (
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                {label}
                <Box sx={{ flex: 1 }} />
                <Switch
                    size="small"
                    checked={value}
                    onChange={(e) => onField(e.target.checked)}
                    sx={{ height: CONTROL_HEIGHT, "& .MuiSwitch-switchBase": { top: 3 } }}
                />
            </Box>
        );
    }

    if (typeof value === "number") {
        return (
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                {label}
                <TextField
                    size="small"
                    type="number"
                    defaultValue={String(value)}
                    onBlur={(e) => onField(parseValue(e.target.value, value))}
                    sx={{
                        width: 160,
                        "& .MuiOutlinedInput-root": { height: CONTROL_HEIGHT },
                        "& .MuiOutlinedInput-input": { padding: "0 14px", lineHeight: "20px" },
                    }}
                    slotProps={{ input: { sx: { fontSize: 14 } } }}
                />
            </Box>
        );
    }

    if (Array.isArray(value)) {
        const isScanner = descriptor?.editor === "scanner";
        return (
            <ListField
                label={label}
                value={value}
                remote={remote}
                addMode={isScanner ? "scanner" : "text"}
                scannerOptions={isScanner ? descriptor.options : undefined}
                onChange={onField}
            />
        );
    }

    return (
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            {label}
            <TextField
                size="small"
                defaultValue={value === null || value === undefined ? "" : String(value)}
                onBlur={(e) => onField(e.target.value)}
                sx={{
                    width: 280,
                    "& .MuiOutlinedInput-root": { height: CONTROL_HEIGHT },
                    "& .MuiOutlinedInput-input": { padding: "0 14px", lineHeight: "20px" },
                }}
                slotProps={{ input: { sx: { fontSize: 14 } } }}
            />
        </Box>
    );
}

function ObjectFieldsEditor({
    value,
    onField,
    fields,
}: {
    value: Record<string, unknown>;
    onField: (field: string, next: unknown) => void;
    fields?: Record<string, FieldDescriptor>;
}) {
    const remote = typeof value.remote === "string" ? value.remote.length > 0 : Boolean(value.remote);

    return (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
            {Object.entries(value).map(([field, fieldValue]) => (
                <FieldRow
                    key={field}
                    field={field}
                    value={fieldValue}
                    remote={remote}
                    descriptor={fields?.[field]}
                    onField={(next) => onField(field, next)}
                />
            ))}
        </Box>
    );
}

function ItemActions({
    index,
    count,
    onMove,
    onRemove,
}: {
    index: number;
    count: number;
    onMove: (direction: -1 | 1) => void;
    onRemove: () => void;
}) {
    return (
        <>
            <IconButton size="small" disabled={index === 0} onClick={() => onMove(-1)} title="Move up">
                <ArrowUpwardIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" disabled={index === count - 1} onClick={() => onMove(1)} title="Move down">
                <ArrowDownwardIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" onClick={onRemove} title="Remove">
                <DeleteIcon fontSize="small" sx={{ color: "error.main" }} />
            </IconButton>
        </>
    );
}

function detectListKind(value: unknown[]): "scalar" | "map" | "named-map" {
    const records = value.filter((item) => isRecord(item));

    if (records.length === 0) {
        return "scalar";
    }

    if (records.every((record) => Object.keys(record).length === 1 && isRecord(Object.values(record)[0]))) {
        return "named-map";
    }

    return "map";
}

const itemCardStyle = {
    display: "flex",
    alignItems: "center",
    gap: 0.5,
    px: 1,
    py: 0.25,
    border: 1,
    borderColor: "divider",
    borderRadius: 1,
} as const;

function ListField({
    label,
    value,
    onChange,
    remote = false,
    item,
    addMode = "text",
    scannerOptions,
}: {
    label: ReactNode;
    value: unknown[];
    onChange: (next: unknown[]) => void;
    remote?: boolean;
    item?: ConfigNode["item"];
    addMode?: "text" | "scanner";
    scannerOptions?: ScannerDefinition[];
}) {
    const items = value;
    const kind =
        item?.kind === "scalar" || item?.kind === "map" || item?.kind === "named-map"
            ? item.kind
            : detectListKind(items);
    const scalarType =
        item?.scalar_type ?? (typeof items[0] === "number" ? "number" : typeof items[0] === "boolean" ? "bool" : "string");

    const [expanded, setExpanded] = useState<number[]>([]);
    const toggleExpanded = (index: number) =>
        setExpanded((prev) => (prev.includes(index) ? prev.filter((i) => i !== index) : [...prev, index]));
    const open = (index: number) => expanded.includes(index);

    const [draft, setDraft] = useState("");

    const cardItems = addMode === "scanner" ? items.filter((v): v is string => typeof v === "string") : items;

    const addScalar = () => {
        if (!draft.trim()) {
            return;
        }

        onChange([...items, parseScalarValue(draft, scalarType)]);
        setDraft("");
    };

    const setAt = (index: number, op: (item: unknown) => unknown) =>
        onChange(items.map((item, i) => (i === index ? op(item) : item)));

    if (kind === "map" || kind === "named-map") {
        return (
            <Box sx={{ display: "flex", flexDirection: "column", gap: 1, width: "100%" }}>
                <Typography sx={{ fontSize: 14, fontWeight: 500 }}>{label}</Typography>

                {items.map((entry, index) => {
                    if (!isRecord(entry)) {
                        return null;
                    }

                    const fields = Object.entries(entry);
                    const isNamed = kind === "named-map" && fields.length === 1 && isRecord(fields[0][1]);
                    const itemName = isNamed ? fields[0][0] : undefined;
                    const itemSettings = (isNamed ? fields[0][1] : entry) as Record<string, unknown>;

                    return (
                        <Box key={index} sx={{ border: 1, borderColor: "divider", borderRadius: 1, overflow: "hidden" }}>
                            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, px: 1, py: 0.5 }}>
                                {isNamed && (
                                    <IconButton size="small" onClick={() => toggleExpanded(index)} title="Expand">
                                        <ExpandMoreIcon
                                            fontSize="small"
                                            sx={{ transform: open(index) ? "rotate(0deg)" : "rotate(-90deg)" }}
                                        />
                                    </IconButton>
                                )}
                                {isNamed ? (
                                    <TextField
                                        size="small"
                                        value={itemName ?? ""}
                                        onChange={(e) =>
                                            setAt(index, (it) => (isRecord(it) ? renameRecordKey(it, e.target.value) : it))
                                        }
                                        placeholder="Pipeline name"
                                        sx={{
                                            flex: 1,
                                            "& .MuiOutlinedInput-root": { height: CONTROL_HEIGHT },
                                            "& .MuiOutlinedInput-input": { padding: "0 14px", lineHeight: "20px" },
                                        }}
                                        slotProps={{ input: { sx: { fontSize: 14 } } }}
                                    />
                                ) : (
                                    <Typography sx={{ fontSize: 14, flex: 1 }}>{formatLabel(`Item ${index + 1}`)}</Typography>
                                )}
                                {isNamed && Boolean(itemSettings.remote) && (
                                    <Chip label={String(itemSettings.remote)} size="small" color="primary" variant="outlined" sx={{ height: 24 }} />
                                )}
                                <ItemActions
                                    index={index}
                                    count={items.length}
                                    onMove={(direction) => onChange(moveIndex(items, index, index + direction))}
                                    onRemove={() => onChange(removeIndex(items, index))}
                                />
                            </Box>

                            {isNamed ? (
                                <Collapse in={open(index)}>
                                    <Box sx={{ px: 1, pb: 1, pt: 0.5 }}>
                                        <ObjectFieldsEditor
                                            value={itemSettings}
                                            fields={item?.fields}
                                            onField={(field, next) =>
                                                setAt(index, (it) =>
                                                    isRecord(it) ? setNestedField(it, itemName ?? "", field, next) : it,
                                                )
                                            }
                                        />
                                    </Box>
                                </Collapse>
                            ) : (
                                <Box sx={{ px: 1, pb: 1 }}>
                                    <ObjectFieldsEditor
                                        value={entry}
                                        fields={item?.fields}
                                        onField={(field, next) =>
                                            setAt(index, (it) => (isRecord(it) ? setRecordField(it, field, next) : it))
                                        }
                                    />
                                </Box>
                            )}
                        </Box>
                    );
                })}

                <Box>
                    <Button
                        size="small"
                        startIcon={<AddIcon />}
                        onClick={() => {
                            const next = [...items, cloneTemplate(item)];
                            onChange(next);
                            setExpanded((prev) => [...prev, next.length - 1]);
                        }}
                    >
                        Add {typeof label === "string" && label.endsWith("s") ? label.slice(0, -1) : label}
                    </Button>
                </Box>
            </Box>
        );
    }

    return (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 0.5, minWidth: 0, flex: 1 }}>
            {label}
            {cardItems.map((cardItem, index) => (
                <Box key={`${index}-${String(cardItem)}`} sx={itemCardStyle}>
                    <Chip label={String(cardItem)} size="small" variant="outlined" sx={{ flex: 1 }} />
                    <ItemActions
                        index={index}
                        count={cardItems.length}
                        onMove={(direction) => onChange(moveIndex(cardItems, index, index + direction))}
                        onRemove={() => onChange(removeIndex(cardItems, index))}
                    />
                </Box>
            ))}

            {addMode === "scanner" && scannerOptions ? (
                <Chooser
                    value={items.filter((v): v is string => typeof v === "string")}
                    remote={remote}
                    options={scannerOptions}
                    onAdd={(name) => onChange([...cardItems, name])}
                />
            ) : (
                <Box sx={{ display: "flex", gap: 0.5 }}>
                    <TextField
                        size="small"
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") {
                                e.preventDefault();
                                addScalar();
                            }
                        }}
                        placeholder="Add value (Enter)"
                        sx={{
                            flex: 1,
                            "& .MuiOutlinedInput-root": { height: CONTROL_HEIGHT },
                            "& .MuiOutlinedInput-input": { padding: "0 14px", lineHeight: "20px" },
                        }}
                        slotProps={{ input: { sx: { fontSize: 14 } } }}
                    />
                    <IconButton size="small" onClick={addScalar} sx={{ alignSelf: "center" }}>
                        <AddIcon fontSize="small" />
                    </IconButton>
                </Box>
            )}
        </Box>
    );
}

function ConfigListField({
    label,
    node,
    nodePath,
    onListUpdate,
}: {
    label: string;
    node: ConfigNode;
    nodePath: string[];
    onListUpdate: (nodePath: string[], op: (list: unknown[]) => unknown[]) => void;
}) {
    const items = Array.isArray(node.value) ? node.value : [];

    return (
        <ListField
            label={label}
            value={items}
            item={node.item ?? undefined}
            onChange={(next) => onListUpdate(nodePath, () => next)}
        />
    );
}

function ConfigLeafField({
    name,
    node,
    path,
    onUpdate,
    onListUpdate,
}: {
    name: string;
    node: ConfigNode;
    path: string[];
    onUpdate: (path: string[], value: unknown) => void;
    onListUpdate: (nodePath: string[], op: (list: unknown[]) => unknown[]) => void;
}) {
    if (Array.isArray(node.value)) {
        return <ConfigListField label={formatLabel(name)} node={node} nodePath={path} onListUpdate={onListUpdate} />;
    }

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
                    sx={{ height: CONTROL_HEIGHT, "& .MuiSwitch-switchBase": { top: 3 } }}
                />
            </Box>
        );
    }

    return (
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <Typography sx={{ fontSize: 14, minWidth: 120 }}>{formatLabel(name)}</Typography>
            {node.description && (
                <Typography sx={{ fontSize: 12, color: "text.secondary", flex: 1, minWidth: 0 }}>{node.description}</Typography>
            )}
            <TextField
                size="small"
                sx={{
                    width: 320,
                    flexShrink: 0,
                    "& .MuiOutlinedInput-root": { height: CONTROL_HEIGHT },
                    "& .MuiOutlinedInput-input": { padding: "0 14px", lineHeight: "20px" },
                }}
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
    onListUpdate,
}: {
    name: string;
    node: ConfigNode;
    path: string[];
    onUpdate: (path: string[], value: unknown) => void;
    onListUpdate: (nodePath: string[], op: (list: unknown[]) => unknown[]) => void;
}) {
    const children = node.children ?? {};
    const childrenCount = Object.keys(children).length;

    if (childrenCount > 0) {
        return (
            <Accordion disableGutters>
                <AccordionSummary
                    expandIcon={<ExpandMoreIcon />}
                    sx={{
                        minHeight: 0,
                        px: 1,
                        "&.Mui-expanded": { minHeight: 0 },
                        "& .MuiAccordionSummary-content": { margin: "6px 0" },
                        "&.Mui-expanded .MuiAccordionSummary-content": { margin: "6px 0" },
                    }}
                >
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
                            onListUpdate={onListUpdate}
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
            <ConfigLeafField name={name} node={node} path={path} onUpdate={onUpdate} onListUpdate={onListUpdate} />
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

    const handleListUpdate = useCallback((nodePath: string[], op: (list: unknown[]) => unknown[]) => {
        setEdited((prev) => (prev ? updateListNode(prev, nodePath, op) : prev));
    }, []);

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
                        {Array.isArray(selectedNode.value) ? (
                            <ConfigListField
                                label={formatLabel(selected!)}
                                node={selectedNode}
                                nodePath={[selected!]}
                                onListUpdate={handleListUpdate}
                            />
                        ) : (
                            Object.entries(selectedNode.children ?? {}).map(([name, node]) => (
                                <ConfigChildRow
                                    key={name}
                                    name={name}
                                    node={node}
                                    path={[selected!, name]}
                                    onUpdate={handleUpdate}
                                    onListUpdate={handleListUpdate}
                                />
                            ))
                        )}
                    </Box>
                </>
            ) : (
                <Typography color="text.secondary">Select a section on the left.</Typography>
            )}
        </SectionPage>
    );
}
