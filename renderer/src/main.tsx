import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { installBrowserShim } from './lib/shim'
import { StoreProvider } from './lib/store'
import './styles.css'

installBrowserShim()

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <StoreProvider>
      <App />
    </StoreProvider>
  </React.StrictMode>
)
