/**
 * Sidecar Python : lance le backend IRIS (exécutable PyInstaller en production, venv en développement),
 * attend l'annonce `IRIS_READY {...}` sur stdout et surveille le process.
 */
import { spawn, ChildProcess } from 'child_process'
import { EventEmitter } from 'events'
import { existsSync, mkdirSync, createWriteStream, WriteStream, statSync, renameSync, readdirSync, unlinkSync } from 'fs'
import { join, resolve } from 'path'
import { app } from 'electron'

export interface BackendInfo {
  host: string
  port: number
  token: string
  data_dir: string
  baseUrl: string
  wsUrl: string
}

const READY_TIMEOUT_MS = 60_000
// Journal technique (constat du 2026-09-14) : il n'est pas chiffré. Il tourne donc : un fichier par jour,
// au plus JOURNAL_MAX_OCTETS chacun, et rien de plus vieux que JOURNAL_JOURS jours n'est gardé. Le service
// reçoit son dossier (IRIS_JOURNAL_TECHNIQUE) pour le vider à l'effacement à distance et à la rétention.
const JOURNAL_MAX_OCTETS = 5 * 1024 * 1024
const JOURNAL_JOURS = 7

export class BackendProcess extends EventEmitter {
  info: BackendInfo | null = null
  private child: ChildProcess | null = null
  private log: WriteStream | null = null
  private logOctets = 0
  private stopping = false
  readonly dataDir: string
  readonly logPath: string
  readonly logDir: string

  constructor(userData: string) {
    super()
    this.dataDir = join(userData, 'iris-data')
    const logDir = join(userData, 'logs')
    mkdirSync(logDir, { recursive: true })
    this.logDir = logDir
    this.logPath = join(logDir, 'backend.log')
  }

  /** Met de côté le journal courant (backend-<horodatage>.log) quand il date d'un autre jour ou devient trop
   *  gros, puis supprime les journaux mis de côté depuis plus de JOURNAL_JOURS jours. Ne lève jamais : un
   *  journal qui ne tourne pas ne doit pas empêcher IRIS de démarrer. */
  private tournerJournal(force = false): void {
    try {
      if (existsSync(this.logPath)) {
        const infos = statSync(this.logPath)
        const autreJour = new Date(infos.mtimeMs).toDateString() !== new Date().toDateString()
        if (force || autreJour || infos.size > JOURNAL_MAX_OCTETS) {
          const horodatage = new Date().toISOString().replace(/[:.]/g, '-')
          renameSync(this.logPath, join(this.logDir, `backend-${horodatage}.log`))
        }
      }
      const limite = Date.now() - JOURNAL_JOURS * 24 * 3600 * 1000
      for (const nom of readdirSync(this.logDir)) {
        if (!/^backend-.*\.log$/.test(nom)) continue
        const chemin = join(this.logDir, nom)
        try {
          if (statSync(chemin).mtimeMs < limite) unlinkSync(chemin)
        } catch {
          /* fichier occupé : il partira au prochain démarrage */
        }
      }
    } catch {
      /* ignore */
    }
  }

  private ecrireJournal(texte: string): void {
    if (!this.log) return
    this.log.write(texte)
    this.logOctets += Buffer.byteLength(texte)
    if (this.logOctets > JOURNAL_MAX_OCTETS) {
      // Trop gros en cours de route : on ferme, on met de côté et on repart d'un fichier vide.
      const ancien = this.log
      this.log = null
      this.logOctets = 0
      ancien.end(() => {
        this.tournerJournal(true)
        this.log = createWriteStream(this.logPath, { flags: 'a' })
      })
    }
  }

  private resolveCommand(): { cmd: string; args: string[]; cwd: string } {
    const override = process.env.IRIS_BACKEND_CMD
    if (override) {
      const [cmd, ...args] = override.split(' ')
      return { cmd, args: [...args, '--data-dir', this.dataDir], cwd: process.cwd() }
    }
    if (app.isPackaged) {
      const dir = join(process.resourcesPath, 'backend')
      const exe = process.platform === 'win32' ? 'iris-backend.exe' : 'iris-backend'
      return { cmd: join(dir, exe), args: ['--data-dir', this.dataDir], cwd: dir }
    }
    const backendDir = resolve(app.getAppPath(), 'backend')
    const venvPython =
      process.platform === 'win32'
        ? join(backendDir, '.venv', 'Scripts', 'python.exe')
        : join(backendDir, '.venv', 'bin', 'python')
    const python = existsSync(venvPython) ? venvPython : process.platform === 'win32' ? 'python' : 'python3'
    return { cmd: python, args: ['-m', 'iris', '--data-dir', this.dataDir], cwd: backendDir }
  }

  start(): Promise<BackendInfo> {
    this.stopping = false
    const { cmd, args, cwd } = this.resolveCommand()
    this.tournerJournal()
    this.log = createWriteStream(this.logPath, { flags: 'a' })
    this.logOctets = 0
    this.ecrireJournal(`\n[${new Date().toISOString()}] start: ${cmd} ${args.join(' ')}\n`)

    return new Promise<BackendInfo>((resolvePromise, reject) => {
      let settled = false
      const fail = (err: Error): void => {
        if (!settled) {
          settled = true
          reject(err)
        }
      }
      let child: ChildProcess
      try {
        child = spawn(cmd, args, {
          cwd,
          windowsHide: true,
          // IRIS_AUTO_SETUP : autorise le backend à préparer une vraie session (modèle vocal, accès
          // VELA). Réservé au lancement par l'application : ni les tests ni les scripts ne
          // doivent télécharger 41 Mo ni joindre le relais.
          env: {
            ...process.env,
            PYTHONIOENCODING: 'utf-8',
            PYTHONUNBUFFERED: '1',
            IRIS_AUTO_SETUP: '1',
            IRIS_JOURNAL_TECHNIQUE: this.logDir
          },
          stdio: ['ignore', 'pipe', 'pipe']
        })
      } catch (err) {
        fail(err as Error)
        return
      }
      this.child = child
      const timer = setTimeout(() => fail(new Error(`Le backend IRIS n'a pas démarré en ${READY_TIMEOUT_MS / 1000}s (voir ${this.logPath})`)), READY_TIMEOUT_MS)

      let buffer = ''
      child.stdout?.setEncoding('utf-8')
      child.stdout?.on('data', (chunk: string) => {
        // L'annonce IRIS_READY porte le jeton maître local : elle n'entre jamais dans le journal.
        this.ecrireJournal(chunk.replace(/IRIS_READY [^\n]*/g, 'IRIS_READY (annonce reçue, jeton non journalisé)'))
        buffer += chunk
        let idx: number
        while ((idx = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, idx).trim()
          buffer = buffer.slice(idx + 1)
          if (line.startsWith('IRIS_READY ')) {
            try {
              const raw = JSON.parse(line.slice('IRIS_READY '.length))
              const info: BackendInfo = {
                host: raw.host,
                port: raw.port,
                token: raw.token,
                data_dir: raw.data_dir,
                baseUrl: `http://${raw.host}:${raw.port}`,
                wsUrl: `ws://${raw.host}:${raw.port}/ws?token=${encodeURIComponent(raw.token)}`
              }
              this.info = info
              clearTimeout(timer)
              settled = true
              this.emit('ready', info)
              resolvePromise(info)
            } catch (err) {
              // Jamais la ligne brute (elle contient le jeton) dans le message d'erreur.
              fail(new Error('Annonce du backend illisible.'))
            }
          }
        }
      })
      child.stderr?.setEncoding('utf-8')
      child.stderr?.on('data', (chunk: string) => {
        this.ecrireJournal(chunk)
        if (!app.isPackaged) process.stderr.write(`[backend] ${chunk}`)
      })
      child.on('error', (err) => {
        this.ecrireJournal(`spawn error: ${err.message}\n`)
        clearTimeout(timer)
        fail(new Error(`Impossible de lancer le backend IRIS (${cmd}) : ${err.message}`))
      })
      child.on('exit', (code, signal) => {
        this.ecrireJournal(`[${new Date().toISOString()}] exit code=${code} signal=${signal}\n`)
        clearTimeout(timer)
        this.child = null
        const wasReady = this.info !== null
        this.info = null
        if (!wasReady) fail(new Error(`Le backend IRIS s'est arrêté avant d'être prêt (code ${code}). Voir ${this.logPath}`))
        if (!this.stopping) this.emit('exit', { code, signal })
      })
    })
  }

  stop(): void {
    this.stopping = true
    const child = this.child
    if (!child || child.killed) return
    try {
      if (process.platform === 'win32' && child.pid) {
        spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true })
      } else {
        child.kill('SIGTERM')
      }
    } catch {
      /* ignore */
    }
    this.child = null
    this.info = null
  }
}
