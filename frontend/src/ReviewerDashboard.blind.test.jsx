import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ReviewerDashboard from './ReviewerDashboard';
vi.mock('./NotificationBell', () => ({ default: () => null }));
vi.mock('./ReviewerProfilePanel', () => ({ default: () => null }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
it('shows download for a minimal accepted assignment and reports unavailable artifact', async () => {
  const jsonHeaders = new Headers({ 'content-type': 'application/json' });
  vi.stubGlobal('fetch', vi.fn(async url => url.endsWith('/assignments/my')
    ? { ok: true, headers: jsonHeaders, json: async () => [{ assignment_id: 4, manuscript_id: 3, review_round: 1, status: 'assigned', invitation_status: 'accepted', review_file_available: true }] }
    : url.endsWith('/progress') ? { ok: true, headers: jsonHeaders, json: async () => ({ manuscript_id: 3, review_round: 1, stages: [] }) }
    : { ok: false, headers: jsonHeaders, json: async () => ({ detail: 'Review file unavailable' }) }));
  render(<ReviewerDashboard user={{ user_id: 1, name: 'Synthetic' }} token="synthetic" />);
  await userEvent.click(await screen.findByRole('button', { name: 'Open manuscript' }));
  expect(await screen.findByRole('list', {name:'Workflow timeline'})).toBeTruthy();
  await userEvent.click(await screen.findByRole('button', { name: 'Download Review File' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Review file unavailable');
  expect(screen.queryByText(/Invalid Date/)).toBeNull();
});


it('returns the actual reviewer assignment to the list with a protected title fallback', async () => {
  const headers=new Headers({'content-type':'application/json'});
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,headers,json:async()=>url.endsWith('/assignments/my') ? [1,2].map(id=>({assignment_id:id,manuscript_id:id,review_round:1,status:'assigned',invitation_status:'accepted'})) : {manuscript_id:1,review_round:1,stages:[]}})));
  let goBack; const register=handler=>{goBack=handler;return ()=>{};};
  render(<ReviewerDashboard user={{user_id:1,name:'Synthetic'}} token="synthetic" registerManuscriptReturn={register} />);
  const first=(await screen.findByText('Manuscript #1')).closest('.reviewer-card');
  fireEvent.click(within(first).getByRole('button',{name:'Open manuscript'}));
  expect(screen.queryByText('Manuscript #2')).toBeNull();
  expect(screen.getByRole('heading',{name:'Manuscript #1'}).closest('[data-workspace=selected]')).toBeTruthy();
  expect(within(screen.getByRole('heading',{name:'Manuscript #1'}).closest('[data-workspace=selected]')).getAllByText('Manuscript #1')).toHaveLength(1);
  act(()=>{expect(goBack()).toBe(true);});
  expect(screen.getByText('Manuscript #2')).toBeTruthy();
});


it('ignores a delayed manuscript A detail failure after switching to B', async () => {
  let resolveA;
  const headers=new Headers({'content-type':'application/json'});
  vi.stubGlobal('fetch',vi.fn(url=> {
    if(url.endsWith('/assignments/my')) return Promise.resolve({ok:true,headers,json:async()=>[1,2].map(id=>({assignment_id:id,manuscript_id:id,review_round:1,status:'assigned',invitation_status:'accepted'}))});
    if(url.endsWith('/manuscripts/1')) return new Promise(resolve=>{resolveA=resolve;});
    if(url.endsWith('/progress')) return Promise.resolve({ok:true,headers,json:async()=>({manuscript_id:url.includes('/1/')?1:2,review_round:1,stages:[]})});
    return Promise.resolve({ok:false,headers,json:async()=>({detail:'unavailable'})});
  }));
  render(<ReviewerDashboard user={{user_id:1,name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByRole('heading',{name:'Manuscript #1'})).closest('.reviewer-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByRole('button',{name:'View manuscript details'}));
  fireEvent.click(screen.getByRole('button',{name:'Back to Manuscripts'}));
  fireEvent.click(within(screen.getByRole('heading',{name:'Manuscript #2'}).closest('.reviewer-card')).getByRole('button',{name:'Open manuscript'}));
  await act(async()=>resolveA({ok:false,headers,json:async()=>({detail:'STALE A ERROR'})}));
  await waitFor(()=>expect(screen.queryByText('STALE A ERROR')).toBeNull());
  expect(screen.getByRole('heading',{name:'Manuscript #2'})).toBeTruthy();
});

it('refreshes denied downloads and keeps unsaved review text', async () => {
  const headers = new Headers({ 'content-type': 'application/json' });
  let loads = 0;
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/assignments/my')) {
      loads += 1;
      return { ok: true, headers, json: async () => [{ assignment_id: 4, manuscript_id: 3, review_round: 1, status: 'assigned', invitation_status: 'accepted', review_file_available: loads === 1 }] };
    }
    if (url.endsWith('/progress')) return { ok: true, headers, json: async () => ({ manuscript_id: 3, stages: [] }) };
    return { ok: false, headers, json: async () => ({ detail: 'Review file unavailable' }) };
  }));
  render(<ReviewerDashboard user={{ user_id: 1, name: 'Synthetic' }} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Open manuscript' }));
  fireEvent.change(screen.getByLabelText(/Review Comments/), { target: { value: 'Unsaved review' } });
  fireEvent.click(screen.getByRole('button', { name: 'Download Review File' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Review file unavailable');
  expect(screen.queryByRole('button', { name: 'Download Review File' })).toBeNull();
  expect(screen.getByLabelText(/Review Comments/).value).toBe('Unsaved review');
});

it('ignores stale assignment responses after a token change', async () => {
  const headers = new Headers({ 'content-type': 'application/json' });
  let resolveOld;
  vi.stubGlobal('fetch', vi.fn((url, options) => {
    if (url.endsWith('/assignments/my') && options.headers.Authorization === 'Bearer old') return new Promise(resolve => { resolveOld = resolve; });
    return Promise.resolve({ ok: true, headers, json: async () => [{ assignment_id: 2, manuscript_id: 2, review_round: 1, status: 'assigned', invitation_status: 'accepted', review_file_available: false }] });
  }));
  const { rerender } = render(<ReviewerDashboard user={{ user_id: 1, name: 'Synthetic' }} token="old" />);
  await waitFor(() => expect(resolveOld).toBeDefined());
  rerender(<ReviewerDashboard user={{ user_id: 1, name: 'Synthetic' }} token="new" />);
  expect(await screen.findByRole('heading', { name: 'Manuscript #2' })).toBeTruthy();
  await act(async () => resolveOld({ ok: true, headers, json: async () => [{ assignment_id: 1, manuscript_id: 1, review_round: 1, status: 'assigned', invitation_status: 'accepted', review_file_available: true }] }));
  expect(screen.queryByRole('heading', { name: 'Manuscript #1' })).toBeNull();
});

it('clears availability when refreshing fails', async () => {
  const headers = new Headers({ 'content-type': 'application/json' });
  let loads = 0;
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/assignments/my')) {
      loads += 1;
      return loads === 1 ? { ok: true, headers, json: async () => [{ assignment_id: 4, manuscript_id: 3, review_round: 1, status: 'assigned', invitation_status: 'accepted', review_file_available: true }] } : { ok: false, headers, json: async () => ({ detail: 'Refresh failed' }) };
    }
    return { ok: true, headers, json: async () => ({ manuscript_id: 3, stages: [] }) };
  }));
  render(<ReviewerDashboard user={{ user_id: 1, name: 'Synthetic' }} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Open manuscript' }));
  expect(screen.getByRole('button', { name: 'Download Review File' })).toBeTruthy();
  fireEvent.focus(window);
  expect((await screen.findByRole('alert')).textContent).toContain('Refresh failed');
  expect(screen.queryByRole('button', { name: 'Download Review File' })).toBeNull();
});

it('isolates a loaded workspace when reviewer identity changes and refresh fails', async () => {
  const headers = new Headers({ 'content-type': 'application/json' });
  vi.stubGlobal('fetch', vi.fn(async (url, options) => {
    if (url.endsWith('/assignments/my')) return options.headers.Authorization === 'Bearer b'
      ? { ok: false, headers, json: async () => ({ detail: 'B unavailable' }) }
      : { ok: true, headers, json: async () => [{ assignment_id: 1, manuscript_id: 1, review_round: 1, status: 'assigned', invitation_status: 'accepted', review_file_available: true }] };
    return { ok: true, headers, json: async () => url.endsWith('/progress') ? { manuscript_id: 1, stages: [] } : { manuscript_id: 1, review_round: 1, author_name: 'Synthetic A private detail' } };
  }));
  const { rerender } = render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="a" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Open manuscript' }));
  fireEvent.change(screen.getByLabelText(/Review Comments/), { target: { value: 'A private review' } });
  fireEvent.click(screen.getByRole('button', { name: 'View manuscript details' }));
  expect(await screen.findByText(/Synthetic A private detail/)).toBeTruthy();
  rerender(<ReviewerDashboard user={{ user_id: 2, name: 'B' }} token="b" />);
  expect((await screen.findByRole('alert')).textContent).toContain('B unavailable');
  expect(screen.queryByText(/A private review/)).toBeNull();
  expect(screen.queryByText(/Synthetic A private detail/)).toBeNull();
  expect(screen.queryByRole('heading', { name: 'Manuscript #1' })).toBeNull();
  expect(screen.queryByLabelText(/Review Comments/)).toBeNull();
});

it('preserves unsaved review when the same reviewer rotates token', async () => {
  const headers = new Headers({ 'content-type': 'application/json' });
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true, headers, json: async () => url.endsWith('/assignments/my') ? [{ assignment_id: 1, manuscript_id: 1, review_round: 1, status: 'assigned', invitation_status: 'accepted', review_file_available: true }] : { manuscript_id: 1, stages: [] } })));
  const { rerender } = render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="old" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Open manuscript' }));
  fireEvent.change(screen.getByLabelText(/Review Comments/), { target: { value: 'Unsaved' } });
  rerender(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="new" />);
  await waitFor(() => expect(screen.getByLabelText(/Review Comments/).value).toBe('Unsaved'));
});

it('preserves unsaved review after a same-identity refresh failure', async () => {
  const headers = new Headers({ 'content-type': 'application/json' });
  let loads = 0;
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/assignments/my')) return ++loads === 1
      ? { ok: true, headers, json: async () => [{ assignment_id: 1, manuscript_id: 1, review_round: 1, status: 'assigned', invitation_status: 'accepted', review_file_available: true }] }
      : { ok: false, headers, json: async () => ({ detail: 'Refresh failed' }) };
    if (url.endsWith('/download')) return { ok: false, headers, json: async () => ({ detail: 'Denied' }) };
    return { ok: true, headers, json: async () => ({ manuscript_id: 1, stages: [] }) };
  }));
  render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="a" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Open manuscript' }));
  fireEvent.change(screen.getByLabelText(/Review Comments/), { target: { value: 'Unsaved on failure' } });
  fireEvent.click(screen.getByRole('button', { name: 'Download Review File' }));
  await screen.findByRole('alert');
  expect(screen.getByLabelText(/Review Comments/).value).toBe('Unsaved on failure');
  expect(screen.queryByRole('button', { name: 'Download Review File' })).toBeNull();
});

it.each(['selection', 'identity', 'current'])('guards a successful download for %s', async scenario => {
  const headers = new Headers({ 'content-type': 'application/json' });
  let resolveDownload;
  const create = vi.fn(() => 'blob:synthetic');
  const revoke = vi.fn();
  let cleanupUrl;
  const actualTimeout = globalThis.setTimeout;
  if (scenario === 'current') vi.spyOn(globalThis, 'setTimeout').mockImplementation((fn, delay, ...args) => {
    if (delay === 1000) { cleanupUrl = fn; return 1; }
    return actualTimeout(fn, delay, ...args);
  });
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke });
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  vi.stubGlobal('fetch', vi.fn((url, options) => {
    if (url.endsWith('/assignments/my')) return Promise.resolve({ ok: true, headers, json: async () => options.headers.Authorization === 'Bearer b' ? [] : [1, 2].map(id => ({ assignment_id: id, manuscript_id: id, review_round: 1, status: 'assigned', invitation_status: 'accepted', review_file_available: true })) });
    if (url.endsWith('/download')) return new Promise(resolve => { resolveDownload = resolve; });
    return Promise.resolve({ ok: true, headers, json: async () => ({ manuscript_id: 1, stages: [] }) });
  }));
  const { rerender } = render(<ReviewerDashboard user={{ user_id: 1, name: 'A' }} token="a" />);
  fireEvent.click(within((await screen.findByRole('heading', { name: 'Manuscript #1' })).closest('.reviewer-card')).getByRole('button', { name: 'Open manuscript' }));
  fireEvent.click(screen.getByRole('button', { name: 'Download Review File' }));
  await waitFor(() => expect(resolveDownload).toBeDefined());
  if (scenario === 'selection') {
    fireEvent.click(screen.getByRole('button', { name: 'Back to Manuscripts' }));
    fireEvent.click(within(screen.getByRole('heading', { name: 'Manuscript #2' }).closest('.reviewer-card')).getByRole('button', { name: 'Open manuscript' }));
  } else if (scenario === 'identity') {
    rerender(<ReviewerDashboard user={{ user_id: 2, name: 'B' }} token="b" />);
    await screen.findByText('No review assignments found.');
  }
  await act(async () => resolveDownload({ ok: true, headers: new Headers({ 'content-type': 'application/pdf' }), blob: async () => new Blob(['synthetic']) }));
  expect(create).toHaveBeenCalledTimes(scenario === 'current' ? 1 : 0);
  expect(click).toHaveBeenCalledTimes(scenario === 'current' ? 1 : 0);
  if (scenario === 'current') {
    expect(document.querySelector('a[download="review_assignment_1.pdf"]')).toBeNull();
    expect(cleanupUrl).toBeDefined();
    cleanupUrl();
    expect(revoke).toHaveBeenCalledWith('blob:synthetic');
  }
});

it('keeps a review on cancelled return and clears it after confirmed return', async () => {
  const headers=new Headers({'content-type':'application/json'});
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,headers,json:async()=>url.endsWith('/assignments/my')
    ? [1,2].map(id=>({assignment_id:id,manuscript_id:id,review_round:id,status:'assigned',invitation_status:'accepted'}))
    : {manuscript_id:url.includes('/2/')?2:1,review_round:1,stages:[]}})));
  vi.stubGlobal('confirm',vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true));
  let goBack;const register=handler=>{goBack=handler;return ()=>{};};
  render(<ReviewerDashboard user={{user_id:1,name:'Synthetic'}} token="synthetic" registerManuscriptReturn={register} />);
  fireEvent.click(within((await screen.findByRole('heading',{name:'Manuscript #1'})).closest('.reviewer-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.change(screen.getByLabelText(/Review Comments/),{target:{value:'Private draft A'}});
  act(()=>expect(goBack()).toBe(false));
  expect(screen.getByLabelText(/Review Comments/).value).toBe('Private draft A');
  act(()=>expect(goBack()).toBe(true));
  fireEvent.click(within(screen.getByRole('heading',{name:'Manuscript #2'}).closest('.reviewer-card')).getByRole('button',{name:'Open manuscript'}));
  expect(screen.getByLabelText(/Review Comments/).value).toBe('');
  act(()=>expect(goBack()).toBe(true));
  fireEvent.click(within(screen.getByRole('heading',{name:'Manuscript #1'}).closest('.reviewer-card')).getByRole('button',{name:'Open manuscript'}));
  expect(screen.getByLabelText(/Review Comments/).value).toBe('');
});
