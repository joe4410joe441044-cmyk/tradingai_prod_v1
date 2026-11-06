export const PROP_ISOLATED_DEMO_PATH = "/prop-isolated-demo";
export const PROP_ISOLATED_DEMO_FLAG = "VITE_PROP_ISOLATED_DEMO_ENABLED";

export const isPropIsolatedDemoEnabled = (environment = import.meta.env || {}) => (
    environment[PROP_ISOLATED_DEMO_FLAG] === "true"
);

export const PROP_ISOLATED_DEMO_ENABLED = isPropIsolatedDemoEnabled();
