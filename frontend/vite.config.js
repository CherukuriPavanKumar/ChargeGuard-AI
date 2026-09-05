import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite rather than Next.js, deliberately: this is a static demo site with no
// server-rendered routes and no data fetching that needs to run on a server.
// Next would add an SSR runtime, a build step that has to reconcile server and
// client component boundaries, and a deployment target -- for a page that is
// ultimately a folder of assets. `vite build` emits exactly that.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // Chunking note.
    //
    // `three` and `recharts` are deliberately NOT listed in manualChunks.
    // Naming a package there puts its chunk into the entry's static graph, and
    // Vite then emits `<link rel="modulepreload">` for it in index.html --
    // which downloads it at high priority on first paint and defeats the whole
    // point of the `React.lazy` boundaries. Measured: both appeared as preloads
    // and ~375KB gzipped rode along with the initial page.
    //
    // Left to Rollup's automatic splitting, each falls out into its own chunk
    // reached only through the dynamic import that needs it, and neither is
    // preloaded.
    //
    // `framer-motion` stays manual because it is genuinely eager -- the nav,
    // hero, problem and architecture sections all animate -- so a stable vendor
    // chunk is a real caching win rather than a preload hazard.
    rollupOptions: {
      output: {
        manualChunks: {
          motion: ['framer-motion'],
        },
      },
    },
    chunkSizeWarningLimit: 1200,
  },
});
