import { createTheme, CssBaseline, ThemeProvider, useMediaQuery } from "@mui/material";
import { useMemo } from "react";
import type { ReactNode } from "react";
import type {} from "@mui/x-data-grid/themeAugmentation";

export default function AppTheme({ children }: { children: ReactNode }) {
    const prefersDarkMode = useMediaQuery("(prefers-color-scheme: dark)");

    const theme = useMemo(
        () =>
            createTheme({
                palette: {
                    mode: prefersDarkMode ? "dark" : "light",
                    primary: prefersDarkMode
                        ? { main: "#c084fc" }
                        : { main: "#aa3bff" },
                },
                components: {
                    MuiCssBaseline: {
                        styleOverrides: {
                            ":root": {
                                colorScheme: prefersDarkMode ? "dark" : "light",
                            },
                            "*::-webkit-scrollbar": {
                                width: 10,
                                height: 10,
                            },
                            "*::-webkit-scrollbar-thumb": {
                                backgroundColor: prefersDarkMode
                                    ? "rgba(255,255,255,0.35)"
                                    : "rgba(0,0,0,0.35)",
                                borderRadius: 8,
                                border: "2px solid transparent",
                                backgroundClip: "content-box",
                            },
                            "*::-webkit-scrollbar-thumb:hover": {
                                backgroundColor: prefersDarkMode
                                    ? "rgba(255,255,255,0.5)"
                                    : "rgba(0,0,0,0.5)",
                            },
                            "*::-webkit-scrollbar-track": {
                                backgroundColor: prefersDarkMode
                                    ? "rgba(255,255,255,0.06)"
                                    : "rgba(0,0,0,0.05)",
                            },
                            "*": {
                                scrollbarWidth: "thin",
                                scrollbarColor: prefersDarkMode
                                    ? "rgba(255,255,255,0.35) rgba(255,255,255,0.06)"
                                    : "rgba(0,0,0,0.35) rgba(0,0,0,0.05)",
                            },
                        },
                    },
                    MuiDataGrid: {
                        defaultProps: {
                            density: "compact",
                        },
                        styleOverrides: {
                            cell: {
                                fontSize: 13,
                            },
                            columnHeader: {
                                fontSize: 13,
                            },
                        },
                    },
                    MuiTable: {
                        defaultProps: {
                            size: "small",
                        },
                    },
                    MuiTableCell: {
                        styleOverrides: {
                            root: {
                                paddingTop: 4,
                                paddingBottom: 4,
                            },
                            sizeSmall: {
                                padding: "4px 8px",
                            },
                        },
                    },
                },
            }),
        [prefersDarkMode],
    );

    return (
        <ThemeProvider theme={theme}>
            <CssBaseline />
            {children}
        </ThemeProvider>
    );
}
