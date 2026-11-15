import { Fragment } from "react";
import { Box } from "@mui/material";

interface MetadataListProps {
    entries: Array<[string, string]>;
    mono?: boolean;
}

export default function MetadataList({ entries, mono }: MetadataListProps) {
    return (
        <Box
            sx={{
                display: "grid",
                gridTemplateColumns: "auto 1fr",
                gap: "4px 12px",
                fontSize: 13,
            }}
        >
            {entries.map(([key, value]) => (
                <Fragment key={key}>
                    <Box component="dt" sx={{ color: "text.secondary" }}>
                        {key}
                    </Box>
                    <Box component="dd" sx={{ margin: 0, wordBreak: "break-word", fontFamily: mono ? "monospace" : undefined }}>
                        {value}
                    </Box>
                </Fragment>
            ))}
        </Box>
    );
}
