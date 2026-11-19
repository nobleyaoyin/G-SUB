import { useEffect, useRef, useState } from 'react'

// A standalone fixture component, not mounted in the G-SUB application.
export default function SyntheticOnlyofficePage({ adapterOrigin, bearerToken, manuscript = 'synthetic-1' }) {
  const [error, setError] = useState('')
  const instance = useRef(null)

  useEffect(() => {
    let cancelled = false
    let script
    async function start() {
      try {
        const adapter = new URL(adapterOrigin)
        if (adapter.protocol !== 'http:' || adapter.hostname !== '127.0.0.1' || !adapter.port || adapter.pathname !== '/' || adapter.search || adapter.hash) throw new Error('Invalid adapter origin.')
        const response = await fetch(`${adapterOrigin}/manuscripts/${manuscript}/editor`, {
          method: 'POST', headers: { Authorization: `Bearer ${bearerToken}` },
        })
        if (!response.ok) throw new Error('Unable to start the synthetic editing session.')
        const { editorOrigin, config } = await response.json()
        const url = new URL(editorOrigin)
        if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port) throw new Error('Invalid editor origin.')
        if (cancelled) return
        script = document.createElement('script')
        script.src = `${url.origin}/web-apps/apps/api/documents/api.js`
        script.onload = () => {
          if (!cancelled && window.DocsAPI) instance.current = new window.DocsAPI.DocEditor('synthetic-editor', config)
        }
        script.onerror = () => { if (!cancelled) setError('The local document service is unavailable.') }
        document.head.appendChild(script)
      } catch (failure) {
        if (!cancelled) setError(failure.message)
      }
    }
    start()
    return () => {
      cancelled = true
      instance.current?.destroyEditor()
      script?.remove()
    }
  }, [adapterOrigin, bearerToken, manuscript])

  return <section><h1>Synthetic DOCX editing</h1><p>Disposable test documents only. Saving does not submit or approve a manuscript.</p>{error && <p role="alert">{error}</p>}<div style={{ height: '75vh', minHeight: 500 }}><div id="synthetic-editor" /></div></section>
}
