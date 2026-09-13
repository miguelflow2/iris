// Config Vite d'aperçu : sert le renderer seul dans un navigateur (sans Electron),
// pour vérifier l'interface avec un service IRIS lancé à part (?host=&port=&token=).
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const ici = dirname(fileURLToPath(import.meta.url))
export default defineConfig({
  root: ici,
  plugins: [react()],
  resolve: { alias: { '@': resolve(ici, 'src') } },
  server: { port: 5173, strictPort: true }
})
