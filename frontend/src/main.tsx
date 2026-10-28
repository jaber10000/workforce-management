import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { initTheme } from './theme'
import './styles.css'
import './palettes.css'
import './features.css'
import './advanced.css'
import { initEnhance } from './enhance'

initTheme() // set data-theme before first paint → no light/dark flash

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

requestAnimationFrame(initEnhance) // design layer: EN/বাংলা, glow, progress bar
