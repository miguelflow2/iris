import { resolve } from 'path'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      lib: { entry: resolve(__dirname, 'electron/main/index.ts') },
      outDir: 'out/main'
    }
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      lib: { entry: resolve(__dirname, 'electron/preload/index.ts') },
      outDir: 'out/preload'
    }
  },
  renderer: {
    root: resolve(__dirname, 'renderer'),
    plugins: [react()],
    resolve: { alias: { '@': resolve(__dirname, 'renderer/src') } },
    build: {
      outDir: resolve(__dirname, 'out/renderer'),
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'renderer/index.html'),
          indicator: resolve(__dirname, 'renderer/indicator.html')
        }
      }
    }
  }
})
