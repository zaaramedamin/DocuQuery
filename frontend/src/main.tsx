import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { I18nProvider } from './i18n'
import { NotificationsProvider } from './components/Notifications'
import { PreferencesProvider } from './PreferencesProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PreferencesProvider>
      <I18nProvider>
        <NotificationsProvider>
          <App />
        </NotificationsProvider>
      </I18nProvider>
    </PreferencesProvider>
  </StrictMode>,
)
