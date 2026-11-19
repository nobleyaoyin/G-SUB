import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import ReviewerDashboard from './ReviewerDashboard';

vi.mock('./NotificationBell', () => ({ default: () => null }));
vi.mock('./ReviewerProfilePanel', () => ({ default: () => null }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const jsonHeaders = new Headers({ 'content-type': 'application/json' });
const pdfHeaders = new Headers({ 'content-type': 'application/pdf' });
const okJson = value => ({ ok: true, headers: jsonHeaders, json: async () => value });
const okPdf = () => ({ ok: true, headers: pdfHeaders, blob: async () => new Blob(['synthetic']) });
const defer = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const items = [1, 2].map(id => ({ assignment_id: id, manuscript_id: id, review_round: 1, status: 'assigned', invitation_status: 'accepted', review_file_available: true }));
const open = async id => fireEvent.click(within((await screen.findByRole('heading', { name: `Manuscript #${id}` })).closest('.reviewer-card')).getByRole('button', { name: 'Open manuscript' }));
const back = () => fireEvent.click(screen.getByRole('button', { name: 'Back to Manuscripts' }));

it.each([undefined, null, 0, -1, 1.5, NaN, '1', true, Number.MAX_SAFE_INTEGER + 1])('fails closed for invalid reviewer ID %s', id => {
  const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
  render(<ReviewerDashboard user={{ user_id: id, name: 'Synthetic' }} token="synthetic" />);
  expect(screen.getByRole('alert').textContent).toContain('Reviewer account unavailable');
  expect(fetchMock).not.toHaveBeenCalled();
});

it('removes an existing workspace when the identity becomes invalid', async () => {
  const fetchMock = vi.fn(url => url.endsWith('/assignments/my') ? Promise.resolve(okJson(items)) : Promise.resolve(okJson({ manuscript_id: 1, stages: [] })));
  vi.stubGlobal('fetch', fetchMock);
  const view = render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="a" />);
  await open(1);
  fireEvent.change(screen.getByLabelText(/Review Comments/), { target: { value: 'Private review' } });
  const calls = fetchMock.mock.calls.length;
  view.rerender(<ReviewerDashboard user={{ user_id: null, name: 'Invalid' }} token="b" />);
  expect(screen.getByRole('alert').textContent).toContain('Reviewer account unavailable');
  expect(screen.queryByDisplayValue('Private review')).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(calls);
});

it.each(['identity', 'selection', 'unmount'])('does not refresh an old failed download after %s', async change => {
  const pending = defer(); const calls = [];
  vi.stubGlobal('fetch', vi.fn((url, options = {}) => {
    if (url.endsWith('/assignments/my')) { calls.push(options.headers.Authorization); return Promise.resolve(okJson(options.headers.Authorization === 'Bearer b' ? [] : items)); }
    if (url.endsWith('/download')) return pending.promise;
    return Promise.resolve(okJson({ manuscript_id: 1, stages: [] }));
  }));
  const view = render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="a" />);
  await open(1); fireEvent.click(screen.getByRole('button', { name: 'Download Review File' }));
  if (change === 'identity') { view.rerender(<ReviewerDashboard user={{ user_id: 2, name: 'B' }} token="b" />); await screen.findByText('No review assignments found.'); }
  if (change === 'selection') { back(); await open(2); }
  if (change === 'unmount') view.unmount();
  await act(async () => pending.reject(new Error('synthetic failure')));
  expect(calls.filter(token => token === 'Bearer a')).toHaveLength(1);
  if (change === 'identity') expect(screen.getByText('No review assignments found.')).toBeTruthy();
});

it('does not apply a refresh response after the original workspace unmounts', async () => {
  const refreshing = defer(); let aLoads = 0;
  vi.stubGlobal('fetch', vi.fn((url, options = {}) => {
    if (url.endsWith('/assignments/my')) {
      if (options.headers.Authorization === 'Bearer b') return Promise.resolve(okJson([]));
      return ++aLoads === 1 ? Promise.resolve(okJson(items)) : refreshing.promise;
    }
    if (url.endsWith('/download')) return Promise.reject(new Error('synthetic failure'));
    return Promise.resolve(okJson({ manuscript_id: 1, stages: [] }));
  }));
  const view = render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="a" />);
  await open(1); fireEvent.click(screen.getByRole('button', { name: 'Download Review File' }));
  await waitFor(() => expect(aLoads).toBe(2));
  view.rerender(<ReviewerDashboard user={{ user_id: 2, name: 'B' }} token="b" />);
  await screen.findByText('No review assignments found.');
  await act(async () => refreshing.resolve(okJson(items)));
  expect(screen.queryByRole('heading', { name: 'Manuscript #1' })).toBeNull();
  expect(screen.queryByText('synthetic failure')).toBeNull();
});

it('deduplicates the same assignment synchronously in one event cycle', async () => {
  const pending = defer(); let downloads = 0;
  vi.stubGlobal('fetch', vi.fn(url => {
    if (url.endsWith('/assignments/my')) return Promise.resolve(okJson(items));
    if (url.endsWith('/download')) { downloads += 1; return pending.promise; }
    return Promise.resolve(okJson({ manuscript_id: 1, stages: [] }));
  }));
  render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="a" />);
  await open(1);
  const button = screen.getByRole('button', { name: 'Download Review File' });
  act(() => { button.click(); button.click(); });
  expect(downloads).toBe(1);
  await act(async () => pending.reject(new Error('synthetic')));
});

it.each(['first', 'second', 'first-fails'])('keeps overlapping assignment requests owned when %s finishes first', async order => {
  const a = defer(), b = defer(); const create = vi.fn(() => 'blob:synthetic');
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  vi.stubGlobal('fetch', vi.fn(url => {
    if (url.endsWith('/assignments/my')) return Promise.resolve(okJson(items));
    if (url.endsWith('/assignments/1/download')) return a.promise;
    if (url.endsWith('/assignments/2/download')) return b.promise;
    return Promise.resolve(okJson({ manuscript_id: 1, stages: [] }));
  }));
  render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="a" />);
  await open(1); fireEvent.click(screen.getByRole('button', { name: 'Download Review File' }));
  back(); await open(2); fireEvent.click(screen.getByRole('button', { name: 'Download Review File' }));
  expect(screen.getByRole('button', { name: 'Downloading...' }).disabled).toBe(true);
  if (order === 'second') {
    await act(async () => b.resolve(okPdf()));
    expect(click).toHaveBeenCalledTimes(1);
    await act(async () => a.resolve(okPdf()));
  } else {
    if (order === 'first-fails') await act(async () => a.reject(new Error('synthetic')));
    else await act(async () => a.resolve(okPdf()));
    expect(screen.getByRole('button', { name: 'Downloading...' }).disabled).toBe(true);
    await act(async () => b.resolve(okPdf()));
  }
  expect(click).toHaveBeenCalledTimes(1);
  expect(create).toHaveBeenCalledTimes(1);
});

it.each(['create', 'click'])('revokes the URL and removes anchor when %s fails', async failure => {
  const revoke = vi.fn(); let cleanupUrl;
  const actualTimeout = globalThis.setTimeout;
  vi.spyOn(globalThis, 'setTimeout').mockImplementation((fn, delay, ...args) => {
    if (delay === 1000) { cleanupUrl = fn; return 1; }
    return actualTimeout(fn, delay, ...args);
  });
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:synthetic'), revokeObjectURL: revoke });
  if (failure === 'create') {
    const create = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag, ...args) => {
      if (tag === 'a') throw new Error('synthetic anchor creation failure');
      return create(tag, ...args);
    });
  } else vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => { throw new Error('synthetic anchor click failure'); });
  vi.stubGlobal('fetch', vi.fn(url => url.endsWith('/assignments/my') ? Promise.resolve(okJson(items)) : url.endsWith('/download') ? Promise.resolve(okPdf()) : Promise.resolve(okJson({ manuscript_id: 1, stages: [] }))));
  render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="a" />);
  await open(1); fireEvent.click(screen.getByRole('button', { name: 'Download Review File' }));
  await waitFor(() => expect(cleanupUrl).toBeDefined());
  cleanupUrl();
  expect(revoke).toHaveBeenCalledWith('blob:synthetic');
  expect(document.querySelector('a[download="review_assignment_1.pdf"]')).toBeNull();
});

it.each(['create-throws', 'revoke-getter-throws', 'revoke-not-function', 'create-getter-throws'])('does not leak a URL when %s occurs before creation completes', async failure => {
  const create = vi.fn(() => { if (failure === 'create-throws') throw new Error('synthetic create failure'); return 'blob:synthetic'; });
  const revoke = vi.fn();
  const urlApi = { createObjectURL: create, revokeObjectURL: revoke };
  if (failure === 'revoke-getter-throws') Object.defineProperty(urlApi, 'revokeObjectURL', { get() { throw new Error('synthetic getter failure'); } });
  if (failure === 'revoke-not-function') urlApi.revokeObjectURL = null;
  if (failure === 'create-getter-throws') Object.defineProperty(urlApi, 'createObjectURL', { get() { throw new Error('synthetic getter failure'); } });
  vi.stubGlobal('URL', urlApi);
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  vi.stubGlobal('fetch', vi.fn(url => url.endsWith('/assignments/my') ? Promise.resolve(okJson(items)) : url.endsWith('/download') ? Promise.resolve(okPdf()) : Promise.resolve(okJson({ manuscript_id: 1, stages: [] }))));
  render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="a" />);
  await open(1); fireEvent.click(screen.getByRole('button', { name: 'Download Review File' }));
  await screen.findByRole('alert');
  expect(create).toHaveBeenCalledTimes(failure === 'create-throws' ? 1 : 0);
  expect(revoke).not.toHaveBeenCalled();
  expect(click).not.toHaveBeenCalled();
});

it.each(['normal', 'anchor-create', 'anchor-append', 'anchor-click', 'timer-throws', 'revoke-throws', 'timer-calls-then-throws'])('attempts exactly one cleanup for a created URL when %s occurs', async failure => {
  let cleanupUrl;
  const actualTimeout = globalThis.setTimeout;
  vi.spyOn(globalThis, 'setTimeout').mockImplementation((fn, delay, ...args) => {
    if (delay !== 1000 || fn.name !== 'cleanupUrl') return actualTimeout(fn, delay, ...args);
    if (failure === 'timer-throws') throw new Error('synthetic timer failure');
    if (failure === 'timer-calls-then-throws') { fn(); throw new Error('synthetic timer failure'); }
    cleanupUrl = fn;
    return 1;
  });
  const urlApi = {};
  const create = vi.fn(function () { expect(this).toBe(urlApi); return 'blob:synthetic'; });
  const revoke = vi.fn(function () { expect(this).toBe(urlApi); if (failure === 'revoke-throws') throw new Error('synthetic revoke failure'); });
  urlApi.createObjectURL = create; urlApi.revokeObjectURL = revoke;
  vi.stubGlobal('URL', urlApi);
  if (failure === 'anchor-create') {
    const actualCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag, ...args) => {
      if (tag === 'a') throw new Error('synthetic anchor creation failure');
      return actualCreate(tag, ...args);
    });
  }
  if (failure === 'anchor-append') {
    const append = document.body.appendChild.bind(document.body);
    vi.spyOn(document.body, 'appendChild').mockImplementation(node => {
      if (node.tagName === 'A') throw new Error('synthetic append failure');
      return append(node);
    });
  }
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {
    if (failure === 'anchor-click') throw new Error('synthetic click failure');
  });
  vi.stubGlobal('fetch', vi.fn(url => url.endsWith('/assignments/my') ? Promise.resolve(okJson(items)) : url.endsWith('/download') ? Promise.resolve(okPdf()) : Promise.resolve(okJson({ manuscript_id: 1, stages: [] }))));
  render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="a" />);
  await open(1); fireEvent.click(screen.getByRole('button', { name: 'Download Review File' }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
  if (failure !== 'timer-throws' && failure !== 'timer-calls-then-throws') {
    await waitFor(() => expect(cleanupUrl).toBeDefined());
    expect(revoke).not.toHaveBeenCalled();
    expect(() => { cleanupUrl(); cleanupUrl(); }).not.toThrow();
  }
  expect(revoke).toHaveBeenCalledTimes(1);
  expect(revoke).toHaveBeenCalledWith('blob:synthetic');
  expect(document.querySelector('a[download="review_assignment_1.pdf"]')).toBeNull();
  expect(click).toHaveBeenCalledTimes(failure === 'anchor-create' || failure === 'anchor-append' ? 0 : 1);
});
