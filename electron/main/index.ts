import { app, BrowserWindow, dialog, globalShortcut, ipcMain, Menu, nativeImage, Notification, screen, shell, Tray } from 'electron'
import { readFileSync, writeFileSync, existsSync } from 'fs'
import { basename, extname, join } from 'path'
import { BackendProcess, type BackendInfo } from './backend'
import { BackendLink } from './link'
import { IndicatorWindow, type CaptureState } from './indicator'
import { is } from './is'
import { cameraActive, decisionDecrire, libelleMenuDecrire, MESSAGE_LUNETTES_REQUISES, phraseRefus, URL_ACHAT_LUNETTES } from './decrire'

let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null
let backend: BackendProcess
let link: BackendLink
let indicator: IndicatorWindow
let quitting = false
let backendRestarts = 0
let restarting = false
let voiceRunning = false

/**
 * Démarrage avec la session Windows. IRIS doit être vivante en continu sur la machine : si l'utilisateur
 * doit penser à la lancer, elle n'est plus un assistant présent mais une application de plus à ouvrir.
 * Ignoré en développement, où l'on ne veut pas inscrire le binaire de test au démarrage.
 */
function applyAutoStart(enabled: boolean | undefined): void {
  if (enabled === undefined || !app.isPackaged) return
  try {
    const actuel = app.getLoginItemSettings().openAtLogin
    if (actuel !== enabled) {
      app.setLoginItemSettings({ openAtLogin: enabled, args: ['--hidden'] })
    }
  } catch (err) {
    console.error('[iris] démarrage automatique :', err)
  }
}
let privacyMode = false
let micMuted = false
let inviteActif = false
let descriptionEnCours = false
// Dit par le service (GET /api/lunettes/presence, événement lunettes.presence) ; faux tant qu'il ne l'a pas dit.
let cameraLunettesActive = false

const APP_ICON = join(__dirname, '../../build/icon.png')

function icon(size?: number): Electron.NativeImage {
  const img = existsSync(APP_ICON) ? nativeImage.createFromPath(APP_ICON) : nativeImage.createEmpty()
  return size && !img.isEmpty() ? img.resize({ width: size, height: size }) : img
}

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => showMainWindow())
}

app.setAppUserModelId('com.vela.iris')

function createMainWindow(): BrowserWindow {
  // Format portrait, façon téléphone : c'est ainsi que l'interface est dessinée. La hauteur
  // s'adapte aux petits écrans ; l'utilisateur peut agrandir, la colonne reste centrée.
  const zone = screen.getPrimaryDisplay().workAreaSize
  const win = new BrowserWindow({
    width: Math.min(640, zone.width),
    height: Math.min(980, zone.height - 40),
    minWidth: 420,
    minHeight: 600,
    show: false,
    title: 'IRIS',
    backgroundColor: '#0c0c0c',
    icon: icon(),
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      spellcheck: true
    }
  })
  win.once('ready-to-show', () => win.show())
  win.on('close', (event) => {
    if (!quitting) {
      event.preventDefault()
      win.hide() // reste dans la barre système : l'écoute vocale continue
    }
  })
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'))
  }
  return win
}

function showMainWindow(): void {
  if (!mainWindow || mainWindow.isDestroyed()) mainWindow = createMainWindow()
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

function buildTrayMenu(): Menu {
  return Menu.buildFromTemplate([
    { label: 'Ouvrir IRIS', click: () => showMainWindow() },
    { type: 'separator' },
    {
      label: voiceRunning ? 'Pause de l’écoute (10 min)' : 'Reprendre l’écoute vocale',
      click: () => link.send({ type: voiceRunning ? 'voice.pause' : 'voice.start', minutes: 10 })
    },
    { label: 'Parler maintenant (Ctrl+Maj+Espace)', click: () => link.send({ type: 'voice.push_to_talk' }) },
    { label: libelleMenuDecrire(cameraLunettesActive), click: () => decrireDevantMoi() },
    { label: 'Stop (couper la parole)', click: () => link.send({ type: 'tts.stop' }) },
    { label: micMuted ? 'Réactiver le micro (Ctrl+Maj+M)' : 'Micro muet (Ctrl+Maj+M)', type: 'checkbox', checked: micMuted, click: () => link.send({ type: 'voice.toggle_mute' }) },
    { type: 'separator' },
    { label: 'Mode confidentiel (micro coupé)', type: 'checkbox', checked: privacyMode, click: () => link.send({ type: 'privacy.toggle' }) },
    // « mémoire suspendue », pas « rien n'est mémorisé » : rappels et tâches créés pendant la session restent (mode_invite.py).
    { label: 'Mode invité (mémoire suspendue)', type: 'checkbox', checked: inviteActif, click: () => basculerInvite() },
    { type: 'separator' },
    { label: 'Quitter IRIS', click: () => app.quit() }
  ])
}

function createTray(): void {
  tray = new Tray(icon(16))
  tray.setToolTip('IRIS — prête')
  tray.setContextMenu(buildTrayMenu())
  tray.on('click', () => showMainWindow())
}

function registerShortcuts(): void {
  globalShortcut.register('CommandOrControl+Shift+Space', () => link.send({ type: 'voice.push_to_talk' }))
  globalShortcut.register('CommandOrControl+Shift+I', () => showMainWindow())
  globalShortcut.register('CommandOrControl+Shift+M', () => link.send({ type: 'voice.toggle_mute' }))
  globalShortcut.register('CommandOrControl+Shift+S', () => link.send({ type: 'tts.stop' }))
  // Un raccourci déjà pris par une autre application n'est pas une panne : on le note, sans plus.
  if (!globalShortcut.register('CommandOrControl+Shift+D', () => decrireDevantMoi())) {
    console.error('[iris] raccourci Ctrl+Maj+D indisponible (déjà utilisé par une autre application)')
  }
}

function notify(title: string, body: string): void {
  if (Notification.isSupported()) new Notification({ title, body, icon: icon(64) }).show()
}

/* ---------------------------------------------------------------------------
   Appels directs au service local, depuis le process principal : le raccourci et
   la barre système marchent fenêtre fermée, là où le renderer ne tourne pas. Le
   WebSocket (link.ts) ne porte que des commandes vocales ; décrire et le mode
   invité sont des routes HTTP, appelées avec le même jeton de session.
   --------------------------------------------------------------------------- */
interface ReponseService {
  ok: boolean
  status: number
  data: any
}

async function appelService(method: 'GET' | 'POST', path: string, body?: unknown, delaiMs = 15000): Promise<ReponseService> {
  const info = backend?.info
  if (!info) return { ok: false, status: 0, data: { detail: 'Le service IRIS n’est pas démarré.' } }
  const controle = new AbortController()
  const minuterie = setTimeout(() => controle.abort(), delaiMs)
  try {
    const res = await fetch(`${info.baseUrl}${path}`, {
      method,
      headers: { Authorization: `Bearer ${info.token}`, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controle.signal
    })
    let data: any = null
    try {
      data = await res.json()
    } catch {
      data = null
    }
    return { ok: res.ok, status: res.status, data }
  } catch (err) {
    const expire = (err as Error)?.name === 'AbortError'
    return { ok: false, status: 0, data: { detail: expire ? 'IRIS n’a pas répondu à temps.' : 'Le service IRIS est injoignable.' } }
  } finally {
    clearTimeout(minuterie)
  }
}

/** Retient ce que le service dit de la caméra des lunettes et remet le menu de la barre système à jour. */
function noterCameraLunettes(presence: any): void {
  const active = cameraActive(presence)
  if (active === cameraLunettesActive) return
  cameraLunettesActive = active
  tray?.setContextMenu(buildTrayMenu())
}

/**
 * Le choix « Retenir la description dans ma mémoire » de l'écran Accessibilité, gardé par la fenêtre
 * (localStorage, clé iris.accessibilite.retenir, « true » ou « false ») : le raccourci suit le même choix que
 * l'écran, y compris sa valeur par défaut (retenir). La fenêtre fermée est seulement cachée : son renderer
 * tourne encore et répond. Choix illisible (fenêtre détruite, stockage bloqué, pas de réponse en 1 s) : rien
 * n'est retenu, car un raccourci ne doit pas remplir la mémoire sur une supposition. La mémoire suspendue
 * (mode invité, zone sans mémoire) est de toute façon respectée par le service.
 */
async function lireChoixRetenir(): Promise<boolean> {
  const fenetre = mainWindow
  if (!fenetre || fenetre.isDestroyed()) return false
  try {
    const lecture = fenetre.webContents.executeJavaScript(
      "(() => { try { return { valeur: window.localStorage.getItem('iris.accessibilite.retenir') } } catch { return null } })()",
      false
    ) as Promise<{ valeur: string | null } | null>
    const reponse = await Promise.race([lecture, new Promise<null>((r) => setTimeout(() => r(null), 1000))])
    if (!reponse || typeof reponse !== 'object') return false
    return reponse.valeur !== 'false'
  } catch {
    return false
  }
}

/**
 * « Décrire devant moi » (Ctrl+Maj+D et barre système). Lunettes d'abord : sans lunettes présentes,
 * rien d'autre qu'une notification — aucune capture d'écran de repli, aucun appel de description.
 * Caméra des lunettes non activée par le service (camera_lunettes_active=false) : aucune photo n'est
 * demandée ; la notification dit la limite et où décrire une image ou l'écran (electron/main/decrire.ts).
 */
async function decrireDevantMoi(): Promise<void> {
  if (descriptionEnCours) {
    notify('IRIS', 'Une description est déjà en cours.')
    return
  }
  descriptionEnCours = true
  try {
    const presence = await appelService('GET', '/api/lunettes/presence')
    if (presence.ok) noterCameraLunettes(presence.data)
    const decision = decisionDecrire(presence)
    if ('notifier' in decision) {
      notify(decision.notifier.titre, decision.notifier.corps)
      return
    }
    // Une photo des lunettes prend quelques secondes, puis la description : délai large.
    const memoriser = await lireChoixRetenir()
    const r = await appelService('POST', '/api/accessibilite/decrire', { ...decision.decrire, parler: true, memoriser }, 120000)
    if (r.ok) {
      // La description est lue à voix haute. Son texte n'est PAS recopié dans la notification : Windows garde
      // les notifications dans son Centre de notifications et peut les montrer sur l'écran verrouillé, hors
      // d'IRIS, sans chiffrement, même en mode invité ou dans une zone sans mémoire.
      notify('IRIS — devant vous', 'Description terminée et lue à voix haute.')
      return
    }
    if (r.status === 428) {
      notify('IRIS — lunettes requises', `${phraseRefus(r.data, MESSAGE_LUNETTES_REQUISES)} ${r.data?.detail?.acheter_url || URL_ACHAT_LUNETTES}`)
      return
    }
    notify('IRIS — description impossible', phraseRefus(r.data, 'La description a échoué.'))
  } finally {
    descriptionEnCours = false
  }
}

/** Mode invité depuis la barre système : permis sans lunettes (confidentialité). */
async function basculerInvite(): Promise<void> {
  const cible = !inviteActif
  const r = await appelService('POST', cible ? '/api/confiance/invite/activer' : '/api/confiance/invite/desactiver', {})
  if (r.ok) {
    inviteActif = Boolean(r.data?.actif)
    tray?.setContextMenu(buildTrayMenu())
    return
  }
  notify('IRIS — mode invité', r.status === 404 ? 'Le mode invité n’est pas disponible dans cette version d’IRIS.' : phraseRefus(r.data, 'Le mode invité n’a pas pu changer.'))
  tray?.setContextMenu(buildTrayMenu()) // la case à cocher revient à l'état réel
}

/** État initial du mode invité, pour que la case de la barre système dise vrai dès le démarrage. */
async function lireInvite(): Promise<void> {
  const r = await appelService('GET', '/api/confiance/invite')
  if (r.ok) {
    inviteActif = Boolean(r.data?.actif)
    tray?.setContextMenu(buildTrayMenu())
  }
}

function wireLink(): void {
  link = new BackendLink()
  link.on('capture', (state: CaptureState) => {
    indicator.update(state)
    tray?.setToolTip(state.mic ? 'IRIS — micro actif' : 'IRIS — prête')
  })
  link.on('event', (event: { type: string; [k: string]: unknown }) => {
    if (event.type === 'voice.state') {
      voiceRunning = Boolean((event as { running?: boolean }).running)
      micMuted = Boolean((event as { muted?: boolean }).muted)
      tray?.setContextMenu(buildTrayMenu())
    }
    if (event.type === 'voice.muted') {
      micMuted = Boolean((event as { muted?: boolean }).muted)
      tray?.setContextMenu(buildTrayMenu())
      tray?.setToolTip(micMuted ? 'IRIS — micro coupé' : 'IRIS — prête')
    }
    if (event.type === 'privacy.mode') {
      privacyMode = Boolean((event as { enabled?: boolean }).enabled)
      tray?.setContextMenu(buildTrayMenu())
      tray?.setToolTip(privacyMode ? 'IRIS — mode confidentiel (micro coupé)' : 'IRIS — prête')
    }
    if (event.type === 'settings.updated') {
      const s = (event as { settings?: { privacy_mode?: boolean; start_with_windows?: boolean } }).settings || {}
      privacyMode = Boolean(s.privacy_mode)
      tray?.setContextMenu(buildTrayMenu())
      applyAutoStart(s.start_with_windows)
    }
    if (event.type === 'task.updated') {
      const task = event.task as { status: string; title: string }
      if (task.status === 'done') notify('IRIS — tâche terminée', task.title)
      if (task.status === 'failed') notify('IRIS — tâche échouée', task.title)
    }
    if (event.type === 'chat.confirm') {
      showMainWindow()
    }
    // Notifications natives : elles arrivent même fenêtre fermée, pendant que le renderer dort.
    if (event.type === 'alerte.sonore') {
      const e = event as { libelle?: string; confiance?: number; test?: boolean }
      const confiance = typeof e.confiance === 'number' ? ` (confiance ${Math.round(e.confiance * 100)} %)` : ''
      notify(e.test ? 'IRIS — essai d’alerte sonore' : 'IRIS — alerte sonore', `${e.libelle || 'Son important détecté'}${confiance}. Vérifiez autour de vous.`)
    }
    // Corps génériques : ni le nom de la personne, ni le texte du rappel, ni le message du proche ne sont
    // recopiés dans l'historique des notifications de Windows (voir decrireDevantMoi). Le détail reste
    // dans IRIS : écran Rappels et messages de la Vision partagée.
    if (event.type === 'rappel.contexte') {
      notify('IRIS — rappel', 'Un rappel lié à une personne s’est déclenché. Ouvrez IRIS pour le lire.')
    }
    if (event.type === 'partage.message') {
      notify('IRIS — vision partagée', 'Nouveau message de votre proche, lu à voix haute. Il s’affiche aussi dans IRIS pendant le partage.')
    }
    if (event.type === 'invite.etat') {
      inviteActif = Boolean((event as { actif?: boolean }).actif)
      tray?.setContextMenu(buildTrayMenu())
    }
    if (event.type === 'lunettes.presence' && 'camera_lunettes_active' in event) {
      noterCameraLunettes(event)
    }
    if (event.type === 'hello') {
      lireInvite().catch(() => undefined)
      appelService('GET', '/api/lunettes/presence')
        .then((r) => {
          if (r.ok) noterCameraLunettes(r.data)
        })
        .catch(() => undefined)
    }
  })
}

async function startBackend(): Promise<BackendInfo> {
  backend = new BackendProcess(app.getPath('userData'))
  backend.on('exit', async () => {
    mainWindow?.webContents.send('iris:backend-status', { state: 'down' })
    if (quitting) return
    if (backendRestarts >= 3) {
      // L'application abandonne : le renderer doit cesser d'afficher « elle redémarre toute
      // seule », sinon l'écran ment. Le statut part AVANT la boîte de dialogue modale.
      const message = `Le service IRIS s'est arrêté de façon répétée. Consultez ${backend.logPath}.`
      mainWindow?.webContents.send('iris:backend-status', { state: 'failed', message })
      dialog.showErrorBox('IRIS', message)
      return
    }
    backendRestarts += 1
    try {
      const info = await backend.start()
      link.connect(info)
      mainWindow?.webContents.send('iris:backend', info)
    } catch (err) {
      mainWindow?.webContents.send('iris:backend-status', { state: 'failed', message: String(err) })
      dialog.showErrorBox('IRIS', String(err))
    }
  })
  return backend.start()
}

/**
 * Relance demandée par l'utilisateur (bouton « Relancer IRIS » des écrans de démarrage et de
 * panne). L'ordre compte : on retire d'abord l'écouteur `exit` de l'ancien sidecar, sinon son
 * arrêt déclencherait la relance automatique en plus de celle-ci (deux backends), puis on
 * referme la liaison WebSocket avant d'en ouvrir une neuve (sinon les événements arrivent en
 * double).
 */
async function restartBackend(): Promise<{ ok: boolean; message?: string }> {
  if (restarting) return { ok: false, message: 'Une relance est déjà en cours.' }
  restarting = true
  try {
    backend?.removeAllListeners('exit')
    backend?.stop()
    backendRestarts = 0
    // Le sidecar est tué de force : on laisse Windows libérer le fichier SQLite et le port
    // avant d'en lancer un neuf sur le même dossier de données.
    await new Promise((r) => setTimeout(r, 400))
    const info = await startBackend()
    link.close()
    link.connect(info)
    mainWindow?.webContents.send('iris:backend', info)
    return { ok: true }
  } catch (err) {
    const message = String(err)
    mainWindow?.webContents.send('iris:backend-status', { state: 'failed', message })
    return { ok: false, message }
  } finally {
    restarting = false
  }
}

app.whenReady().then(async () => {
  if (!gotLock) return
  indicator = new IndicatorWindow()
  wireLink()
  mainWindow = createMainWindow()
  createTray()
  registerShortcuts()
  try {
    const info = await startBackend()
    link.connect(info)
    mainWindow.webContents.send('iris:backend', info)
  } catch (err) {
    dialog.showErrorBox('IRIS — démarrage impossible', String(err))
    mainWindow.webContents.send('iris:backend-status', { state: 'failed', message: String(err) })
  }
})

// ---- IPC exposés au renderer via le preload ---------------------------------
ipcMain.handle('iris:getBackend', () => backend?.info ?? null)
ipcMain.handle('iris:app', () => ({
  version: app.getVersion(),
  platform: process.platform,
  userData: app.getPath('userData'),
  logPath: backend?.logPath ?? '',
  // Version installée ou code source : certains guides (scripts du dossier « scripts ») n'existent qu'avec le code source.
  isPackaged: app.isPackaged
}))
ipcMain.handle('iris:openExternal', (_event, url: string) => {
  if (/^https?:\/\//.test(url)) shell.openExternal(url)
})
ipcMain.handle('iris:openPath', (_event, path: string) => shell.openPath(path))
ipcMain.handle('iris:pickImage', async () => {
  const result = await dialog.showOpenDialog({
    title: 'Joindre une image',
    properties: ['openFile'],
    filters: [{ name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp'] }]
  })
  if (result.canceled || !result.filePaths[0]) return null
  const file = result.filePaths[0]
  const ext = extname(file).toLowerCase().replace('.', '')
  const mediaType = ext === 'jpg' ? 'image/jpeg' : `image/${ext}`
  const data = readFileSync(file).toString('base64')
  if (data.length > 6_000_000) throw new Error('Image trop volumineuse (max ~4 Mo).')
  return { name: basename(file), media_type: mediaType, data }
})
ipcMain.handle('iris:saveFile', async (_event, payload: { name: string; content: string }) => {
  const result = await dialog.showSaveDialog({ defaultPath: payload.name })
  if (result.canceled || !result.filePath) return null
  writeFileSync(result.filePath, payload.content, 'utf-8')
  return result.filePath
})
ipcMain.on('iris:window', (_event, action: string) => {
  if (!mainWindow) return
  if (action === 'minimize') mainWindow.minimize()
  else if (action === 'maximize') mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize()
  else if (action === 'close') mainWindow.close()
})
ipcMain.handle('iris:pushToTalk', () => link.send({ type: 'voice.push_to_talk' }))
ipcMain.handle('iris:restartBackend', () => restartBackend())

app.on('before-quit', () => {
  quitting = true
  globalShortcut.unregisterAll()
  link?.close()
  indicator?.destroy()
  backend?.stop()
})
app.on('window-all-closed', () => {
  /* reste actif dans la barre système */
})
app.on('activate', () => showMainWindow())
