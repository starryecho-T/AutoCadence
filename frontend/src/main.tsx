import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary onReset={() => location.reload()} resetLabel="重新加载">
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)
