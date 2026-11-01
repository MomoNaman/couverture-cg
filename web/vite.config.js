import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base relative : le build fonctionne aussi bien sur GitHub Pages que depuis un dossier local
export default defineConfig({ plugins: [react()], base: "./" });
