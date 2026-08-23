import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import AppTheme from './theme.tsx'
import SlideshowApp from './SlideshowApp.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppTheme>
      <SlideshowApp />
    </AppTheme>
  </StrictMode>,
)
