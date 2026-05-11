import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],

  server: {
    port: 5173,

    proxy: {
      "/api": {
        target: "http://35.194.104.74:8001",
        changeOrigin: true,
        secure: false
      }
    }
  }
});