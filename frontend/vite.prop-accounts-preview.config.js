import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendDirectory = fileURLToPath(new URL(".", import.meta.url));
const dependencyRoot = process.env.TRADINGAI_FRONTEND_NODE_MODULES
    || resolve(frontendDirectory, "node_modules");

export default {
    root: resolve(frontendDirectory, "prop-accounts-preview"),
    base: "./",
    publicDir: false,
    resolve: {
        alias: [
            { find: /^react$/, replacement: resolve(dependencyRoot, "react/index.js") },
            { find: /^react\/jsx-runtime$/, replacement: resolve(dependencyRoot, "react/jsx-runtime.js") },
            { find: /^react-dom\/client$/, replacement: resolve(dependencyRoot, "react-dom/client.js") },
        ],
    },
    build: {
        outDir: resolve(frontendDirectory, "../tmp/cc-2s-prop-preview-dist"),
        emptyOutDir: true,
    },
    server: {
        host: "127.0.0.1",
        port: 4187,
        strictPort: true,
    },
    preview: {
        host: "127.0.0.1",
        port: 4187,
        strictPort: true,
    },
};
