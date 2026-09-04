/**
 * Indicateur de capture logiciel non désactivable (MVP en attendant le voyant physique OEM).
 * Fenêtre flottante sans bordure, toujours au premier plan, sans bouton de fermeture ;
 * elle n'obéit qu'à l'état de capture publié par le backend.
 */
import { BrowserWindow, screen } from 'electron'
import { join } from 'path'
import { is } from './is'

export interface CaptureState {
  mic: boolean
  screen: boolean
  camera: boolean
  listening: boolean
}

export class IndicatorWindow {
  private win: BrowserWindow | null = null
  private hideTimer: NodeJS.Timeout | null = null
  private state: CaptureState = { mic: false, screen: false, camera: false, listening: false }
  quitting = false

  private create(): BrowserWindow {
    const win = new BrowserWindow({
      width: 236,
      height: 44,
      frame: false,
      transparent: true,
      alwaysOnTop: true,
      skipTaskbar: true,
      resizable: false,
      movable: true,
      minimizable: false,
      maximizable: false,
      closable: false,
      focusable: false,
      hasShadow: false,
      show: false,
      title: 'IRIS — capture en cours',
      webPreferences: {
        preload: join(__dirname, '../preload/index.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: false
      }
    })
    win.setAlwaysOnTop(true, 'screen-saver')
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
    win.setMenu(null)
    win.on('close', (event) => {
      if (!this.quitting) event.preventDefault() // ne peut pas être fermée par l'utilisateur
    })
    const { workArea } = screen.getPrimaryDisplay()
    win.setPosition(workArea.x + workArea.width - 236 - 16, workArea.y + 12)
    if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
      win.loadURL(`${process.env['ELECTRON_RENDERER_URL']}/indicator.html`)
    } else {
      win.loadFile(join(__dirname, '../renderer/indicator.html'))
    }
    win.webContents.on('did-finish-load', () => win.webContents.send('indicator:state', this.state))
    return win
  }

  update(state: CaptureState): void {
    this.state = state
    const active = state.mic || state.screen || state.camera
    if (active) {
      if (this.hideTimer) {
        clearTimeout(this.hideTimer)
        this.hideTimer = null
      }
      if (!this.win || this.win.isDestroyed()) this.win = this.create()
      this.win.webContents.send('indicator:state', state)
      if (!this.win.isVisible()) this.win.showInactive()
      return
    }
    if (this.win && !this.win.isDestroyed()) {
      this.win.webContents.send('indicator:state', state)
      // court délai : une capture d'écran ponctuelle reste visible ~1,5 s
      if (this.hideTimer) clearTimeout(this.hideTimer)
      this.hideTimer = setTimeout(() => {
        if (this.win && !this.win.isDestroyed()) this.win.hide()
      }, 1500)
    }
  }

  destroy(): void {
    this.quitting = true
    if (this.hideTimer) clearTimeout(this.hideTimer)
    if (this.win && !this.win.isDestroyed()) this.win.destroy()
    this.win = null
  }
}
