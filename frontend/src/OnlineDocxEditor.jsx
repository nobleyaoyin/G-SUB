import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { API_URL } from './api'

export default function OnlineDocxEditor({ manuscriptId, stage, token, onDirtyChange, onUseSaved, onSelect, showUnavailable = false }) {
  const [available, setAvailable] = useState(null)
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
  const closeWaitTimer = useRef(null)
  const retryTimer = useRef(null)
  const retrying = useRef(false)
  const statusGeneration = useRef(0)
  const editGeneration = useRef(0)
  const retryEditGeneration = useRef(0)
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
      window.clearTimeout(closeWaitTimer.current)
      window.clearTimeout(retryTimer.current)
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
    if (!session) return
    const controller = new AbortController()
    async function check() {
      const generation = statusGeneration.current
      try {
        const r = await fetch(`${base}/sessions/${session}/status`, {headers:{Authorization:`Bearer ${token}`},signal:controller.signal})
        if (!r.ok) throw new Error('Editing session is unavailable or stale. Close and reopen it.')
        const status = await r.json()
        if (controller.signal.aborted || generation !== statusGeneration.current) return
        if (status.state === 'error' && !retrying.current) { window.clearTimeout(closeWaitTimer.current); setSaveState('error'); setError('The draft could not be saved. Keep the editor open and try Download As to keep a copy.') }
        if (status.state === 'saved' && status.version) {
          const mayConfirm = open || status.closed
          if (mayConfirm) setError(current => ['The draft could not be saved. Keep the editor open and try Download As to keep a copy.', 'Final save has not been confirmed. Check the saved draft before continuing.', 'Retry was not confirmed. Keep the editor open and try Download As to keep a copy.', 'Could not request a new save. Keep the editor open and try Download As to keep a copy.'].includes(current) ? '' : current)
          const previous = confirmedRef.current
          confirmedRef.current = status.version
          setConfirmed(status.version)
          const wasRetrying = retrying.current
          const changedDuringRetry = wasRetrying && editGeneration.current !== retryEditGeneration.current
          if (changedDuringRetry) dirtyBaseline.current = status.version.id
          if (mayConfirm && wasRetrying) { retrying.current = false; window.clearTimeout(retryTimer.current) }
          setSaveState(current => changedDuringRetry ? (current === 'pending' ? 'pending' : 'unsaved') : !mayConfirm && current === 'error' ? current : mayConfirm && wasRetrying ? 'saved' : current === 'error' ? 'saved' : current === 'unsaved' ? current : (dirtyBaseline.current && dirtyBaseline.current === status.version.id ? current : 'saved'))
          if (!previous || previous.id !== status.version.id) loadHistory(controller.signal).catch(() => {})
        }
        if (status.closed) { window.clearTimeout(closeWaitTimer.current); setMessage('Editing session closed. Review the saved draft history.'); setSession(null) }
      } catch (e) { if (!controller.signal.aborted && generation === statusGeneration.current && e.name !== 'AbortError') { setSaveState('error'); setError(e.message); setSession(null) } }
    }
    check()
    const interval = window.setInterval(check, 4000)
    return () => { controller.abort(); window.clearInterval(interval) }
  }, [base, token, open, session, loadHistory])
  useEffect(() => {
    const controller = new AbortController()
    setAvailable(null)
    fetch(`${base}/availability`, {headers:{Authorization:`Bearer ${token}`},signal:controller.signal})
      .then(r => r.ok ? r.json() : {available:false}).then(v => {
        if (!controller.signal.aborted) {
          setAvailable(v.available === true)
          if (v.available === true) loadHistory(controller.signal).catch(() => {})
        }
      })
      .catch(() => { if (!controller.signal.aborted) setAvailable(false) })
    return () => controller.abort()
  }, [base, token, loadHistory])
  async function start(item = null) {
    window.clearTimeout(closeWaitTimer.current)
    window.clearTimeout(retryTimer.current); retrying.current = false
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
            if (event.data) { editGeneration.current += 1; dirtyBaseline.current = confirmedRef.current?.id || null; setSaveState('unsaved') }
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
    window.clearTimeout(retryTimer.current); retrying.current = false
    instance.current?.destroyEditor(); instance.current = null; setOpen(false)
    if (wasPreview) setSession(null)
    setPreviewNumber(null)
    dirtyCallback.current?.(false)
    scriptRef.current?.remove(); scriptRef.current = null
    setMessage(wasPreview ? 'Read-only preview closed.' : 'Editor closed. Final draft saving may take a few seconds; submission and approval are separate.')
    if (!wasPreview) timer.current = window.setTimeout(() => { loadHistory().catch(e => { if (mounted.current) setError(e.message) }) }, 12000)
    if (!wasPreview) closeWaitTimer.current = window.setTimeout(() => {
      if (mounted.current) { setSaveState('error'); setError('Final save has not been confirmed. Check the saved draft before continuing.') }
    }, 30000)
  }
  async function retrySave() {
    if (!session || retrying.current) return
    statusGeneration.current += 1
    retryEditGeneration.current = editGeneration.current
    retrying.current = true
    setSaveState('recovering')
    try {
      const r = await fetch(`${base}/sessions/${session}/retry-save`, {method:'POST',headers:{Authorization:`Bearer ${token}`}})
      if (!r.ok) throw new Error('Could not request a new save. Keep the editor open and try Download As to keep a copy.')
      retryTimer.current = window.setTimeout(() => {
        if (mounted.current && retrying.current) { retrying.current = false; setSaveState('error'); setError('Retry was not confirmed. Keep the editor open and try Download As to keep a copy.') }
      }, 30000)
    } catch (e) {
      retrying.current = false; setSaveState('error'); setError(e.message)
    }
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
  if (available !== true) return showUnavailable ? <p className="wizard-editor-status" role="status">{available === null ? 'Checking DOCX editing availability…' : 'DOCX online editing is unavailable for this document. You can download or replace it.'}</p> : null
  return <section aria-label="Online DOCX editing"><h4>DOCX draft editor</h4><p>G-SUB confirms when a draft is stored. The editor's own save indicator does not confirm G-SUB storage.</p><p>Save creates a draft; submit it separately through the existing workflow.</p>
    {error && <div role="alert" style={{padding:'0.75rem',border:'1px solid #b42318',borderRadius:'7px',background:'#fef2f2',color:'#8f1d14'}}><strong>G-SUB storage not confirmed</strong><p>{error}</p><p>The editor's internal save status does not guarantee that G-SUB stored your changes.</p></div>}{message && <p role="status">{message}</p>}
    {!open && session && <p role="status">{saveState === 'error' ? 'Final save not confirmed. You can reopen the last saved draft or wait for a retry.' : 'Final save pending; waiting for server confirmation.'}</p>}
    {!open && <button type="button" disabled={Boolean(session) && saveState !== 'error'} onClick={() => start()}>{session && saveState === 'error' ? 'Reopen last saved draft' : 'Edit DOCX'}</button>}
    {open && <>{previewNumber ? <p>Viewing draft version {previewNumber} (read-only).</p> : <p role="status">{saveState === 'unsaved' ? 'Unsaved editor changes.' : saveState === 'pending' ? 'Save pending; waiting for server confirmation.' : saveState === 'recovering' ? 'Retry requested; waiting for G-SUB storage confirmation.' : saveState === 'saved' ? `Server confirmed draft version ${confirmed?.number}.` : saveState === 'error' ? 'Save status unavailable.' : 'No saved version confirmed for this session.'}</p>}{!previewNumber && saveState === 'error' && <button type="button" onClick={retrySave}>Retry G-SUB save</button>}<div style={{height:'75vh',minHeight:500}}><div id={editorId} /></div><button type="button" onClick={close}>Close editor</button></>}
    {history.length > 0 && <details><summary>DOCX draft history</summary><ol>{history.map(v => <li key={v.id}>Version {v.number} · {v.saved_at} <button type="button" onClick={() => start(v)} disabled={open}>View</button> <button type="button" onClick={() => download(v)}>Download</button> {(onUseSaved || onSelect) && <button type="button" onClick={() => select(v)}>Select for submission</button>}</li>)}</ol></details>}
  </section>
}
