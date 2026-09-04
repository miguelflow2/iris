/**
 * Shim de développement : permet d'ouvrir le renderer dans un navigateur classique
 * (`electron-vite dev --rendererOnly`, URL ?port=…&token=…) sans le pont Electron.
 * Jamais utilisé dans l'application packagée (window.iris est fourni par le preload).
 */
import type { IrisBridge } from '../../../electron/preload'

export function installBrowserShim(): void {
  if (window.iris) return
  const params = new URLSearchParams(window.location.search)
  const host = params.get('host') || '127.0.0.1'
  const port = Number(params.get('port') || 8765)
  const token = params.get('token') || ''
  const info = {
    host,
    port,
    token,
    data_dir: '',
    baseUrl: `http://${host}:${port}`,
    wsUrl: `ws://${host}:${port}/ws?token=${encodeURIComponent(token)}`
  }
  const shim: IrisBridge = {
    getBackend: async () => info,
    onBackend: () => () => undefined,
    onBackendStatus: () => () => undefined,
    appInfo: async () => ({ version: 'dev (navigateur)', platform: navigator.platform, userData: '', logPath: '' }),
    openExternal: async (url) => {
      window.open(url, '_blank')
    },
    openPath: async () => '',
    pickImage: () =>
      new Promise((resolve) => {
        const input = document.createElement('input')
        input.type = 'file'
        input.accept = 'image/*'
        input.onchange = () => {
          const file = input.files?.[0]
          if (!file) return resolve(null)
          const reader = new FileReader()
          reader.onload = () => {
            const data = String(reader.result).split(',')[1] || ''
            resolve({ name: file.name, media_type: file.type || 'image/png', data })
          }
          reader.readAsDataURL(file)
        }
        input.click()
      }),
    saveFile: async (name, content) => {
      const blob = new Blob([content], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = name
      a.click()
      return name
    },
    window: () => undefined,
    restartBackend: async () => ({ ok: false, message: 'Relance impossible depuis le navigateur.' }),
    pushToTalk: async () => {
      await fetch(`${info.baseUrl}/api/voice/push_to_talk`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
      return true
    },
    onIndicatorState: () => () => undefined
  }
  window.iris = shim
}
