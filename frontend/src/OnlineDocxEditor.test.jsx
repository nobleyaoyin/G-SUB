import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import OnlineDocxEditor from './OnlineDocxEditor'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })

it('hides the editing action when the feature is disabled', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok:true,json:async()=>({available:false})}))
  render(<OnlineDocxEditor manuscriptId={1} stage="author" token="synthetic" />)
  await waitFor(() => expect(fetch).toHaveBeenCalled())
  expect(screen.queryByRole('button', {name:'Edit DOCX'})).toBeNull()
})

it('shows a useful error when a configured session cannot be opened', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => url.endsWith('/availability')
    ? {ok:true,json:async()=>({available:true})}
    : url.endsWith('/versions') ? {ok:true,json:async()=>([])}
      : {ok:false,json:async()=>({detail:'Document changed; reopen it'})}))
  render(<OnlineDocxEditor manuscriptId={1} stage="initial" token="synthetic" />)
  fireEvent.click(await screen.findByRole('button', {name:'Edit DOCX'}))
  expect((await screen.findByRole('alert')).textContent).toContain('Document changed')
})

it('loads saved draft history when the panel is reopened', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => url.endsWith('/availability')
    ? {ok:true,json:async()=>({available:true})}
    : {ok:true,json:async()=>([{id:'saved',number:2,saved_at:'synthetic'}])}))
  render(<OnlineDocxEditor manuscriptId={1} stage="author" token="synthetic" />)
  expect(await screen.findByText('DOCX draft history')).toBeTruthy()
  expect(screen.getByText(/Version 2/)).toBeTruthy()
})

it('waits for a newer server-confirmed version after local changes', async () => {
  let callbacks
  let saved = {id:'one',number:1}
  vi.stubGlobal('DocsAPI', {DocEditor: function (_id, config) { callbacks=config.events; this.destroyEditor=vi.fn() }})
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/availability')) return {ok:true,json:async()=>({available:true})}
    if (url.endsWith('/sessions')) return {ok:true,json:async()=>({session:'session',editorOrigin:'http://127.0.0.1:8088',config:{}})}
    if (url.endsWith('/status')) return {ok:true,json:async()=>({state:'saved',version:saved,closed:false})}
    return {ok:true,json:async()=>([])}
  }))
  render(<OnlineDocxEditor manuscriptId={1} stage="author" token="synthetic" />)
  fireEvent.click(await screen.findByRole('button',{name:'Edit DOCX'}))
  await waitFor(() => expect(document.querySelector('script[src$="/documents/api.js"]')).not.toBeNull())
  fireEvent.load(document.querySelector('script[src$="/documents/api.js"]'))
  expect(await screen.findByText('Server confirmed draft version 1.')).toBeTruthy()
  act(() => callbacks.onDocumentStateChange({data:true}))
  expect(screen.getByText('Unsaved editor changes.')).toBeTruthy()
  act(() => callbacks.onDocumentStateChange({data:false}))
  expect(screen.getByText('Save pending; waiting for server confirmation.')).toBeTruthy()
  saved = {id:'two',number:2}
  expect(await screen.findByText('Server confirmed draft version 2.', {}, {timeout:6000})).toBeTruthy()
})


it('explains unavailable DOCX editing without presenting a nonfunctional action', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok:false,status:409,json:async()=>({})}))
  render(<OnlineDocxEditor manuscriptId={1} stage="author" token="synthetic" showUnavailable />)
  expect(await screen.findByText(/DOCX online editing is unavailable/)).toBeTruthy()
  expect(screen.queryByRole('button',{name:'Edit DOCX'})).toBeNull()
})

it('shows a failed save and clears it only after server confirmation', async () => {
  let state = 'error'
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/availability')) return {ok:true,json:async()=>({available:true})}
    if (url.endsWith('/sessions')) return {ok:true,json:async()=>({session:'session',editorOrigin:'http://127.0.0.1:8088',config:{}})}
    if (url.endsWith('/status')) return {ok:true,json:async()=>({state,version:state === 'saved' ? {id:'recovered',number:2} : null,closed:false})}
    return {ok:true,json:async()=>([])}
  }))
  render(<OnlineDocxEditor manuscriptId={1} stage="author" token="synthetic" />)
  fireEvent.click(await screen.findByRole('button',{name:'Edit DOCX'}))
  expect((await screen.findByRole('alert')).textContent).toContain('could not be saved')
  expect(screen.getByRole('alert').textContent).toContain('internal save status does not guarantee')
  expect(screen.queryByText(/Server confirmed draft version/)).toBeNull()
  state = 'saved'
  expect(await screen.findByText('Server confirmed draft version 2.', {}, {timeout:6000})).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
})

it('requests a retry without claiming a save before the callback', async () => {
  let state = 'error'
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/availability')) return {ok:true,json:async()=>({available:true})}
    if (url.endsWith('/sessions')) return {ok:true,json:async()=>({session:'session',editorOrigin:'http://127.0.0.1:8088',config:{}})}
    if (url.endsWith('/retry-save')) return {ok:true,status:202,json:async()=>({state:'requested'})}
    if (url.endsWith('/status')) return {ok:true,json:async()=>({state,version:state === 'saved' ? {id:'recovered',number:2} : null,closed:false})}
    return {ok:true,json:async()=>([])}
  }))
  render(<OnlineDocxEditor manuscriptId={1} stage="author" token="synthetic" />)
  fireEvent.click(await screen.findByRole('button',{name:'Edit DOCX'}))
  fireEvent.click(await screen.findByRole('button',{name:'Retry G-SUB save'}))
  expect(screen.getByText('Retry requested; waiting for G-SUB storage confirmation.')).toBeTruthy()
  expect(screen.queryByText(/Server confirmed draft version/)).toBeNull()
  state = 'saved'
  expect(await screen.findByText('Server confirmed draft version 2.', {}, {timeout:6000})).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
})

it('does not confirm newer edits with the callback for an earlier retry', async () => {
  let state = 'error', saved = {id:'first',number:1}, callbacks
  vi.stubGlobal('DocsAPI', {DocEditor: function (_id, config) { callbacks=config.events; this.destroyEditor=vi.fn() }})
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/availability')) return {ok:true,json:async()=>({available:true})}
    if (url.endsWith('/sessions')) return {ok:true,json:async()=>({session:'session',editorOrigin:'http://127.0.0.1:8088',config:{}})}
    if (url.endsWith('/retry-save')) return {ok:true,status:202,json:async()=>({state:'requested'})}
    if (url.endsWith('/status')) return {ok:true,json:async()=>({state,version:state === 'saved' ? saved : null,closed:false})}
    return {ok:true,json:async()=>([])}
  }))
  render(<OnlineDocxEditor manuscriptId={1} stage="author" token="synthetic" />)
  fireEvent.click(await screen.findByRole('button',{name:'Edit DOCX'}))
  await waitFor(() => expect(document.querySelector('script[src$="/documents/api.js"]')).not.toBeNull())
  fireEvent.load(document.querySelector('script[src$="/documents/api.js"]'))
  fireEvent.click(await screen.findByRole('button',{name:'Retry G-SUB save'}))
  act(() => { callbacks.onDocumentStateChange({data:true}); callbacks.onDocumentStateChange({data:false}) })
  state = 'saved'
  await waitFor(() => expect(fetch.mock.calls.filter(([url]) => url.endsWith('/status')).length).toBeGreaterThanOrEqual(2), {timeout:6000})
  expect(screen.getByText('Save pending; waiting for server confirmation.')).toBeTruthy()
  await new Promise(resolve => setTimeout(resolve, 4200))
  expect(screen.queryByText(/Server confirmed draft version/)).toBeNull()
  saved = {id:'second',number:2}
  expect(await screen.findByText('Server confirmed draft version 2.', {}, {timeout:6000})).toBeTruthy()
}, 18000)

it('ignores a status response that began before the retry request', async () => {
  let calls = 0, resolveOld
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/availability')) return {ok:true,json:async()=>({available:true})}
    if (url.endsWith('/sessions')) return {ok:true,json:async()=>({session:'session',editorOrigin:'http://127.0.0.1:8088',config:{}})}
    if (url.endsWith('/retry-save')) return {ok:true,status:202,json:async()=>({state:'requested'})}
    if (url.endsWith('/status')) {
      calls += 1
      if (calls === 1) return {ok:true,json:async()=>({state:'error',version:null,closed:false})}
      if (calls === 2) return await new Promise(resolve => { resolveOld = resolve })
      return {ok:true,json:async()=>({state:'saved',version:{id:'new',number:2},closed:false})}
    }
    return {ok:true,json:async()=>([])}
  }))
  render(<OnlineDocxEditor manuscriptId={1} stage="author" token="synthetic" />)
  fireEvent.click(await screen.findByRole('button',{name:'Edit DOCX'}))
  await screen.findByRole('button',{name:'Retry G-SUB save'})
  await waitFor(() => expect(resolveOld).toBeTypeOf('function'), {timeout:6000})
  fireEvent.click(screen.getByRole('button',{name:'Retry G-SUB save'}))
  await act(async () => { resolveOld({ok:true,json:async()=>({state:'saved',version:{id:'old',number:1},closed:false})}) })
  expect(screen.queryByText(/Server confirmed draft version/)).toBeNull()
  expect(await screen.findByText('Server confirmed draft version 2.', {}, {timeout:6000})).toBeTruthy()
}, 12000)

it('recovers when a retry confirms the same already-saved version', async () => {
  let state = 'saved', callbacks
  vi.stubGlobal('DocsAPI', {DocEditor: function (_id, config) { callbacks=config.events; this.destroyEditor=vi.fn() }})
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/availability')) return {ok:true,json:async()=>({available:true})}
    if (url.endsWith('/sessions')) return {ok:true,json:async()=>({session:'session',editorOrigin:'http://127.0.0.1:8088',config:{}})}
    if (url.endsWith('/status')) return {ok:true,json:async()=>({state,version:state === 'saved' ? {id:'same',number:1} : null,closed:false})}
    return {ok:true,json:async()=>([])}
  }))
  render(<OnlineDocxEditor manuscriptId={1} stage="author" token="synthetic" />)
  fireEvent.click(await screen.findByRole('button',{name:'Edit DOCX'}))
  await waitFor(() => expect(document.querySelector('script[src$="/documents/api.js"]')).not.toBeNull())
  fireEvent.load(document.querySelector('script[src$="/documents/api.js"]'))
  expect(await screen.findByText('Server confirmed draft version 1.')).toBeTruthy()
  act(() => callbacks.onDocumentStateChange({data:true}))
  state = 'error'
  expect(await screen.findByRole('alert', {}, {timeout:6000})).toBeTruthy()
  state = 'saved'
  expect(await screen.findByText('Server confirmed draft version 1.', {}, {timeout:6000})).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
}, 12000)

it('keeps checking the final save after the editor closes', async () => {
  let state = 'waiting'
  vi.stubGlobal('confirm', () => true)
  vi.stubGlobal('DocsAPI', {DocEditor: function () { this.destroyEditor=vi.fn() }})
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/availability')) return {ok:true,json:async()=>({available:true})}
    if (url.endsWith('/sessions')) return {ok:true,json:async()=>({session:'session',editorOrigin:'http://127.0.0.1:8088',config:{}})}
    if (url.endsWith('/status')) return {ok:true,json:async()=>({state,version:null,closed:false})}
    return {ok:true,json:async()=>([])}
  }))
  render(<OnlineDocxEditor manuscriptId={1} stage="author" token="synthetic" />)
  fireEvent.click(await screen.findByRole('button',{name:'Edit DOCX'}))
  await waitFor(() => expect(document.querySelector('script[src$="/documents/api.js"]')).not.toBeNull())
  fireEvent.load(document.querySelector('script[src$="/documents/api.js"]'))
  fireEvent.click(screen.getByRole('button',{name:'Close editor'}))
  expect(screen.getByText(/Final save pending/)).toBeTruthy()
  expect(screen.getByRole('button',{name:'Edit DOCX'}).disabled).toBe(true)
  state = 'error'
  expect(await screen.findByText(/Final save not confirmed/, {}, {timeout:6000})).toBeTruthy()
  expect(screen.getByRole('button',{name:'Reopen last saved draft'}).disabled).toBe(false)
  expect(screen.queryByText(/Server confirmed draft version/)).toBeNull()
}, 10000)

it('offers recovery when no final callback arrives', async () => {
  let status = {state:'waiting',version:null,closed:false}
  vi.stubGlobal('confirm', () => true)
  vi.stubGlobal('DocsAPI', {DocEditor: function () { this.destroyEditor=vi.fn() }})
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/availability')) return {ok:true,json:async()=>({available:true})}
    if (url.endsWith('/sessions')) return {ok:true,json:async()=>({session:'session',editorOrigin:'http://127.0.0.1:8088',config:{}})}
    if (url.endsWith('/status')) return {ok:true,json:async()=>status}
    return {ok:true,json:async()=>([])}
  }))
  render(<OnlineDocxEditor manuscriptId={1} stage="author" token="synthetic" />)
  fireEvent.click(await screen.findByRole('button',{name:'Edit DOCX'}))
  await waitFor(() => expect(document.querySelector('script[src$="/documents/api.js"]')).not.toBeNull())
  fireEvent.load(document.querySelector('script[src$="/documents/api.js"]'))
  vi.useFakeTimers()
  fireEvent.click(screen.getByRole('button',{name:'Close editor'}))
  await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
  expect(screen.getByText(/Final save has not been confirmed/)).toBeTruthy()
  expect(screen.getByRole('button',{name:'Reopen last saved draft'}).disabled).toBe(false)
  expect(screen.queryByText(/Server confirmed draft version/)).toBeNull()
  status = {state:'saved',version:{id:'old',number:1},closed:false}
  await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
  expect(screen.getByText(/Final save has not been confirmed/)).toBeTruthy()
  status = {state:'saved',version:{id:'new',number:2},closed:true}
  await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
  expect(screen.queryByText(/Final save has not been confirmed/)).toBeNull()
})
