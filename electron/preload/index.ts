import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'

export interface BackendInfo {
  host: string
  port: number
  token: string
  data_dir: string
  baseUrl: string
  wsUrl: string
}

function subscribe<T>(channel: string, cb: (payload: T) => void): () => void {
  const handler = (_event: IpcRendererEvent, payload: T): void => cb(payload)
  ipcRenderer.on(channel, handler)
  return () => ipcRenderer.removeListener(channel, handler)
}

const api = {
  getBackend: (): Promise<BackendInfo | null> => ipcRenderer.invoke('iris:getBackend'),
  onBackend: (cb: (info: BackendInfo) => void) => subscribe<BackendInfo>('iris:backend', cb),
  onBackendStatus: (cb: (status: { state: string; message?: string }) => void) =>
    subscribe<{ state: string; message?: string }>('iris:backend-status', cb),
  appInfo: (): Promise<{ version: string; platform: string; userData: string; logPath: string }> =>
    ipcRenderer.invoke('iris:app'),
  openExternal: (url: string): Promise<void> => ipcRenderer.invoke('iris:openExternal', url),
  openPath: (path: string): Promise<string> => ipcRenderer.invoke('iris:openPath', path),
  pickImage: (): Promise<{ name: string; media_type: string; data: string } | null> => ipcRenderer.invoke('iris:pickImage'),
  saveFile: (name: string, content: string): Promise<string | null> => ipcRenderer.invoke('iris:saveFile', { name, content }),
  window: (action: 'minimize' | 'maximize' | 'close'): void => ipcRenderer.send('iris:window', action),
  pushToTalk: (): Promise<boolean> => ipcRenderer.invoke('iris:pushToTalk'),
  /** Relance le sidecar Python : utilisé par le bouton « Relancer IRIS » des écrans de démarrage et de panne. */
  restartBackend: (): Promise<{ ok: boolean; message?: string }> => ipcRenderer.invoke('iris:restartBackend'),
  onIndicatorState: (cb: (state: { mic: boolean; screen: boolean; camera: boolean; listening: boolean }) => void) =>
    subscribe('indicator:state', cb)
}

export type IrisBridge = typeof api

contextBridge.exposeInMainWorld('iris', api)
