import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { API_URL } from './api'

export default function OnlineDocxEditor({ manuscriptId, stage, token, onDirtyChange, onUseSaved, onSelect }) {
  const [available, setAvailable] = useState(false)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [history, setHistory] = useState([])
  const [session, setSession] = useState(null)
  const [saveState, setSaveState] = useState('waiting')
  const [confirmed, setConfirmed] = useState(null)
  const [previewNumber, setPreviewNumber] = useState(null)
  const dirtyBaseline = useRef(null)
  const confirmedRef = useRef(null)
  const instance = useRef(null)
  const scriptRef = useRef(null)
  const mounted = useRef(true)
  const timer = useRef(null)
  const dirtyCallback = useRef(onDirtyChange)
  useEffect(() => { dirtyCallback.current = onDirtyChange }, [onDirtyChange])
  const editorId = `gsub-docx-${useId().replaceAll(':', '')}`
  const base = `${API_URL}/onlyoffice/manuscripts/${manuscriptId}/${stage}`
  const loadHistory = useCallback(async signal => {
    const r = await fetch(`${base}/versions`, {headers:{Authorization:`Bearer ${token}`},signal})
    if (!r.ok) throw new Error('Draft history unavailable; reopen this manuscript.')
    const value = await r.json()
    if (mounted.current && !signal?.aborted) setHistory(value)
  }, [base, token])
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      window.clearTimeout(timer.current)
      instance.current?.destroyEditor()
      scriptRef.current?.remove()
      dirtyCallback.current?.(false)
    }
  }, [])
  useEffect(() => {
    if (!open) return
    const warn = event => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [open])
  useEffect(() => {
    if (!open || !session) return
    const controller = new AbortController()
    async function check() {
      try {
        const r = await fetch(`${base}/sessions/${session}/status`, {headers:{Authorization:`Bearer ${token}`},signal:controller.signal})
        if (!r.ok) throw new Error('Editing session is unavailable or stale. Close and reopen it.')
        const status = await r.json()
        if (controller.signal.aborted) return
        if (status.state === 'error') { setSaveState('error'); setError('The document server reported a save error.') }
        if (status.state === 'saved' && status.version) {
          const previous = confirmedRef.current
          confirmedRef.current = status.version
          setConfirmed(status.version)
          setSaveState(current => current === 'unsaved' ? current : (dirtyBaseline.current && dirtyBaseline.current === status.version.id ? current : 'saved'))
          if (!previous || previous.id !== status.version.id) loadHistory(controller.signal).catch(() => {})
        }
        if (status.closed) { setMessage('Editing session closed. Review the saved draft history.'); setSession(null) }
      } catch (e) { if (!controller.signal.aborted && e.name !== 'AbortError') { setSaveState('error'); setError(e.message); setSession(null) } }
    }
    check()
    const interval = window.setInterval(check, 4000)
    return () => { controller.abort(); window.clearInterval(interval) }
  }, [base, token, open, session, loadHistory])
  useEffect(() => {
    const controller = new AbortController()
    fetch(`${base}/availability`, {headers:{Authorization:`Bearer ${token}`},signal:controller.signal})
      .then(r => r.ok ? r.json() : {available:false}).then(v => {
        if (!controller.signal.aborted) {
          setAvailable(v.available === true)
          if (v.available === true) loadHistory(controller.signal).catch(() => {})
        }
      })
      .catch(() => {})
    return () => controller.abort()
  }, [base, token, loadHistory])
  async function start(item = null) {
    setError(''); setMessage('')
    try {
      const r = await fetch(item ? `${base}/versions/${encodeURIComponent(item.id)}/preview` : `${base}/sessions`, {method:'POST',headers:{Authorization:`Bearer ${token}`}})
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || 'Editor unavailable')
      const origin = new URL(data.editorOrigin)
      if (origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' || !origin.port) throw new Error('Editor configuration unavailable')
      setOpen(true)
      setPreviewNumber(item?.number ?? null)
      if (!item) {
        dirtyCallback.current?.(true); setSession(data.session); setSaveState('waiting'); setConfirmed(null); confirmedRef.current = null; dirtyBaseline.current = null
        data.config.events = {
          onDocumentStateChange: event => {
            if (event.data) { dirtyBaseline.current = confirmedRef.current?.id || null; setSaveState('unsaved') }
            else setSaveState(current => current === 'unsaved' ? 'pending' : current)
          },
          onError: () => { setSaveState('error'); setError('The document editor reported an error. Check the draft before submitting.') },
        }
      }
      const script = document.createElement('script')
      scriptRef.current = script
      script.src = `${origin.origin}/web-apps/apps/api/documents/api.js`
      script.onload = () => {
        if (!mounted.current || scriptRef.current !== script) return
        if (!window.DocsAPI?.DocEditor) { setError('Document server returned an invalid editor. Close the editor and try again.'); return }
        instance.current = new window.DocsAPI.DocEditor(editorId, data.config)
      }
      script.onerror = () => { if (mounted.current) setError('Document server unavailable. Close the editor and try again.') }
      document.head.appendChild(script)
      await loadHistory()
    } catch (e) { setError(e.message) }
  }
  function close() {
    if (!previewNumber && !window.confirm('Close the editor? Unsaved changes may be lost.')) return
    const wasPreview = previewNumber !== null
    instance.current?.destroyEditor(); instance.current = null; setOpen(false)
    setSession(null); setPreviewNumber(null)
    dirtyCallback.current?.(false)
    scriptRef.current?.remove(); scriptRef.current = null
    setMessage(wasPreview ? 'Read-only preview closed.' : 'Editor closed. Final draft saving may take a few seconds; submission and approval are separate.')
    if (!wasPreview) timer.current = window.setTimeout(() => { loadHistory().catch(e => { if (mounted.current) setError(e.message) }) }, 12000)
  }
  async function download(item) {
    try {
      const r = await fetch(`${base}/versions/${encodeURIComponent(item.id)}`, {headers:{Authorization:`Bearer ${token}`}})
      if (!r.ok) throw new Error('Draft download unavailable')
      const url = URL.createObjectURL(await r.blob()); const a = document.createElement('a')
      a.href = url; a.download = `draft-${item.number}.docx`; a.click(); URL.revokeObjectURL(url)
    } catch (e) { setError(e.message) }
  }
  async function select(item) {
    try {
      const r = await fetch(`${base}/versions/${encodeURIComponent(item.id)}`, {headers:{Authorization:`Bearer ${token}`}})
      if (!r.ok) throw new Error('Draft unavailable; reopen this manuscript')
      const blob = await r.blob()
      onUseSaved?.(new File([blob], 'online-edit.docx', {type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}), `docx:${item.id}`)
      onSelect?.(item.id)
      setMessage(`Draft version ${item.number} selected. Submit separately when ready.`)
    } catch (e) { setError(e.message) }
  }
  if (!available) return null
  return <section aria-label="Online DOCX editing"><h4>DOCX draft editor</h4><p>Save creates a draft; submit it separately through the existing workflow.</p>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {!open && <button type="button" onClick={() => start()}>Edit DOCX</button>}
    {open && <>{previewNumber ? <p>Viewing draft version {previewNumber} (read-only).</p> : <p role="status">{saveState === 'unsaved' ? 'Unsaved editor changes.' : saveState === 'pending' ? 'Save pending; waiting for server confirmation.' : saveState === 'saved' ? `Server confirmed draft version ${confirmed?.number}.` : saveState === 'error' ? 'Save status unavailable.' : 'No saved version confirmed for this session.'}</p>}<div style={{height:'75vh',minHeight:500}}><div id={editorId} /></div><button type="button" onClick={close}>Close editor</button></>}
    {history.length > 0 && <details><summary>DOCX draft history</summary><ol>{history.map(v => <li key={v.id}>Version {v.number} · {v.saved_at} <button type="button" onClick={() => start(v)} disabled={open}>View</button> <button type="button" onClick={() => download(v)}>Download</button> {(onUseSaved || onSelect) && <button type="button" onClick={() => select(v)}>Select for submission</button>}</li>)}</ol></details>}
  </section>
}
