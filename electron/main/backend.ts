/**
 * Sidecar Python : lance le backend IRIS (exécutable PyInstaller en production, venv en développement),
 * attend l'annonce `IRIS_READY {...}` sur stdout et surveille le process.
 */
import { spawn, ChildProcess } from 'child_process'
import { EventEmitter } from 'events'
import { existsSync, mkdirSync, createWriteStream, WriteStream } from 'fs'
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

export class BackendProcess extends EventEmitter {
  info: BackendInfo | null = null
  private child: ChildProcess | null = null
  private log: WriteStream | null = null
  private stopping = false
  readonly dataDir: string
  readonly logPath: string

  constructor(userData: string) {
    super()
    this.dataDir = join(userData, 'iris-data')
    const logDir = join(userData, 'logs')
    mkdirSync(logDir, { recursive: true })
    this.logPath = join(logDir, 'backend.log')
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
    this.log = createWriteStream(this.logPath, { flags: 'a' })
    this.log.write(`\n[${new Date().toISOString()}] start: ${cmd} ${args.join(' ')}\n`)

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
          env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1', IRIS_AUTO_SETUP: '1' },
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
        this.log?.write(chunk)
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
              fail(new Error(`Annonce backend illisible: ${line}`))
            }
          }
        }
      })
      child.stderr?.setEncoding('utf-8')
      child.stderr?.on('data', (chunk: string) => {
        this.log?.write(chunk)
        if (!app.isPackaged) process.stderr.write(`[backend] ${chunk}`)
      })
      child.on('error', (err) => {
        this.log?.write(`spawn error: ${err.message}\n`)
        clearTimeout(timer)
        fail(new Error(`Impossible de lancer le backend IRIS (${cmd}) : ${err.message}`))
      })
      child.on('exit', (code, signal) => {
        this.log?.write(`[${new Date().toISOString()}] exit code=${code} signal=${signal}\n`)
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
