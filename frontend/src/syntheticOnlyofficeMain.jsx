import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import SyntheticOnlyofficePage from './SyntheticOnlyofficePage'

export function Fixture() {
  const [origin, setOrigin] = useState('http://127.0.0.1:8090')
  const [token, setToken] = useState('')
  const [started, setStarted] = useState(false)
  if (started) return <SyntheticOnlyofficePage adapterOrigin={origin} bearerToken={token} />
  return <main><h1>Synthetic ONLYOFFICE fixture</h1><p>Use only a disposable adapter and synthetic credentials.</p><form onSubmit={(event) => { event.preventDefault(); setStarted(true) }}><label>Adapter origin <input value={origin} onChange={(event) => setOrigin(event.target.value)} /></label><label>Synthetic bearer token <input type="password" value={token} onChange={(event) => setToken(event.target.value)} /></label><button type="submit">Open editor</button></form></main>
}

createRoot(document.getElementById('root')).render(<Fixture />)
