/// <reference types="vite/client" />
import type { IrisBridge } from '../../electron/preload'

declare global {
  interface Window {
    iris: IrisBridge
  }
}

export {}
