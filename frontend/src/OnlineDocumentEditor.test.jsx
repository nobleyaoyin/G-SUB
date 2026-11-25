import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OnlineDocumentEditor from './OnlineDocumentEditor';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('opens, saves and reopens the returned synthetic version', async () => {
  let current = { content:'Original', version:'a'.repeat(64), history:[] };
  const fetch = vi.fn(async (_url, options = {}) => {
    if (options.method === 'POST') current = { content:JSON.parse(options.body).content, version:'b'.repeat(64), history:[{number:1, saved_at:'synthetic time', editor:'Author', filename:'v.txt', is_current:true}] };
    return { ok:true, json:async () => options.method === 'POST' ? {message:'saved'} : current };
  });
  vi.stubGlobal('fetch', fetch); const user = userEvent.setup();
  render(<OnlineDocumentEditor manuscriptId={1} token="synthetic" />);
  await user.click(screen.getByRole('button', {name:'Edit document (TXT)'}));
  const field = await screen.findByLabelText('Document text');
  await user.clear(field); await user.type(field, 'New version');
  await user.click(screen.getByRole('button', {name:'Save version'}));
  expect((await screen.findByRole('status')).textContent).toContain('Version saved');
  await user.click(screen.getByText('Version History'));
  expect(screen.getByText(/synthetic time/)).toBeTruthy();
  expect(screen.getByLabelText('Document text').value).toBe('New version');
});

it('warns before discarding edits', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true, json:async () => ({content:'Original',version:'a'.repeat(64),history:[]})})));
  vi.spyOn(window, 'confirm').mockReturnValue(false);
  const user = userEvent.setup(); render(<OnlineDocumentEditor manuscriptId={1} token="synthetic" />);
  await user.click(screen.getByRole('button', {name:'Edit document (TXT)'}));
  const field = await screen.findByLabelText('Document text'); await user.type(field, ' changed');
  await user.click(screen.getByRole('button', {name:'Cancel'}));
  await waitFor(() => expect(screen.getByLabelText('Document text')).toBeTruthy());
  vi.restoreAllMocks();
});

it('does not display a late response from the previous manuscript', async () => {
  let resolveOld;
  vi.stubGlobal('fetch', vi.fn(url => url.includes('/1/')
    ? new Promise(resolve => { resolveOld = resolve; })
    : Promise.resolve({ok:true, json:async () => ({content:'Second manuscript',version:'b'.repeat(64),history:[]})})));
  const user = userEvent.setup();
  const view = render(<OnlineDocumentEditor manuscriptId={1} token="synthetic" />);
  await user.click(screen.getByRole('button', {name:'Edit document (TXT)'}));
  view.rerender(<OnlineDocumentEditor manuscriptId={2} token="synthetic" />);
  expect((await screen.findByLabelText('Document text')).value).toBe('Second manuscript');
  resolveOld({ok:true, json:async () => ({content:'First manuscript',version:'a'.repeat(64),history:[]})});
  await waitFor(() => expect(screen.getByLabelText('Document text').value).toBe('Second manuscript'));
});

it('uses only a revalidated saved editor draft for the submission form', async () => {
  const item={content:'Saved editor text',version:'a'.repeat(64),history:[{number:1,saved_at:'synthetic',editor:'Editor',filename:'v.txt',is_current:true}]};
  const fetch=vi.fn(async () => ({ok:true,json:async()=>item}));vi.stubGlobal('fetch',fetch);
  const selected=vi.fn();const user=userEvent.setup();
  render(<OnlineDocumentEditor manuscriptId={1} token="synthetic" stage="initial" onUseSaved={selected} />);
  await user.click(screen.getByRole('button',{name:'Edit document (TXT)'}));
  await user.click(await screen.findByRole('button',{name:'Use saved draft'}));
  await waitFor(()=>expect(selected).toHaveBeenCalledOnce());
  expect(selected.mock.calls[0][0].name).toBe('online-edit.txt');
  expect(selected.mock.calls[0][1]).toBe(item.version);
  expect(fetch.mock.calls[0][0]).toContain('/eic/manuscripts/1/online-text/initial');
});

it('refuses selection when the saved editor draft changed', async () => {
  let calls=0;vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({content:'Synthetic',version:(++calls===1?'a':'b').repeat(64),history:[{number:1,filename:'v.txt'}]})})));
  const selected=vi.fn();const user=userEvent.setup();render(<OnlineDocumentEditor manuscriptId={1} token="synthetic" stage="final" onUseSaved={selected} />);
  await user.click(screen.getByRole('button',{name:'Edit document (TXT)'}));await user.click(await screen.findByRole('button',{name:'Use saved draft'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Draft changed');expect(selected).not.toHaveBeenCalled();
});

it('reopens a historical draft and keeps the current version as the save base', async () => {
  const item = {content:'Latest',version:'b'.repeat(64),history:[{id:'synthetic-id',number:1,saved_at:'synthetic',editor:'Author',filename:'one.txt',is_current:false}]};
  vi.stubGlobal('fetch',vi.fn(async url => url.includes('/versions/')
    ? {ok:true,text:async()=>'Earlier'} : {ok:true,json:async()=>item}));
  const user=userEvent.setup(); render(<OnlineDocumentEditor manuscriptId={1} token="synthetic" />);
  await user.click(screen.getByRole('button',{name:'Edit document (TXT)'}));
  await screen.findByLabelText('Document text');
  await user.click(screen.getByText('Version History'));
  await user.click(screen.getByRole('button',{name:'Open version'}));
  await waitFor(()=>expect(screen.getByLabelText('Document text').value).toBe('Earlier'));
  expect(screen.getByRole('button',{name:'Save version'}).disabled).toBe(false);
});
