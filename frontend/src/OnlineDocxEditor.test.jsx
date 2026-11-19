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
