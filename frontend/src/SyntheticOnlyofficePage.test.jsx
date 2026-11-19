import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import SyntheticOnlyofficePage from './SyntheticOnlyofficePage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('requests an authorized synthetic editor configuration and loads the local editor', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ editorOrigin: 'http://127.0.0.1:8088', config: {} }) })
  vi.stubGlobal('fetch', fetchMock)
  render(<SyntheticOnlyofficePage adapterOrigin="http://127.0.0.1:8090" bearerToken="synthetic" />)
  await vi.waitFor(() => expect(document.querySelector('script[src="http://127.0.0.1:8088/web-apps/apps/api/documents/api.js"]')).not.toBeNull())
  expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8090/manuscripts/synthetic-1/editor', expect.objectContaining({ method: 'POST' }))
})

it('does not send a token to a non-loopback adapter', async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  render(<SyntheticOnlyofficePage adapterOrigin="http://example.invalid:8090" bearerToken="synthetic" />)
  expect((await screen.findByRole('alert')).textContent).toContain('Invalid adapter origin.')
  expect(fetchMock).not.toHaveBeenCalled()
})
