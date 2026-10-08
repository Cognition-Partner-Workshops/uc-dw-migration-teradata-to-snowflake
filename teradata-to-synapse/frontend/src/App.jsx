import { useEffect, useState } from 'react'
import ScanPage from './pages/ScanPage.jsx'
import InventoryPage from './pages/InventoryPage.jsx'
import ObjectPage from './pages/ObjectPage.jsx'

function parseRoute(hash) {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  if (parts[0] === 'jobs' && parts[1] && parts[2] === 'objects' && parts[3]) {
    return { page: 'object', jobId: parts[1], objectId: Number(parts[3]) }
  }
  if (parts[0] === 'jobs' && parts[1]) return { page: 'inventory', jobId: parts[1] }
  return { page: 'scan' }
}

const STEPS = [
  ['scan', '1. Scan source'],
  ['inventory', '2. Inventory & convert'],
  ['object', '3. Review & download'],
]

export default function App() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash))

  useEffect(() => {
    const onHash = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/">
          <span className="brand-td">Teradata</span>
          <span className="arrow">→</span>
          <span className="brand-az">Azure Synapse</span>
          <span className="brand-sub">migration tool</span>
        </a>
        <nav className="steps">
          {STEPS.map(([key, label]) => (
            <span key={key} className={`step ${route.page === key ? 'active' : ''}`}>
              {label}
            </span>
          ))}
        </nav>
      </header>
      <main className="content">
        {route.page === 'scan' && <ScanPage />}
        {route.page === 'inventory' && <InventoryPage jobId={route.jobId} />}
        {route.page === 'object' && <ObjectPage jobId={route.jobId} objectId={route.objectId} />}
      </main>
    </div>
  )
}
