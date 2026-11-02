import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// The server runs this bundle in an embedded JS engine so Python and the editor
// share one expression parser/printer. Keep it free of React and DOM imports.
export default defineConfig({
    build: {
        emptyOutDir: true,
        outDir: fileURLToPath(new URL("./dist-expression", import.meta.url)),
        lib: {
            entry: fileURLToPath(new URL("./src/lib/expression/standalone.ts", import.meta.url)),
            name: "TrailframeExpression",
            formats: ["iife"],
            fileName: () => "expression.js",
        },
    },
});
