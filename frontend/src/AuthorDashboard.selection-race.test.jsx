import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import AuthorDashboard from './AuthorDashboard';

vi.mock('./NotificationBell', () => ({default: () => null}));
vi.mock('./InitialEditingPanel', () => ({default: () => null}));
vi.mock('./AuthorAgreementPanel', () => ({default: () => null}));
vi.mock('./FinalEditingPanel', () => ({default: () => null}));
vi.mock('./FormattingPanel', () => ({default: () => null}));
vi.mock('./ManuscriptProgress', () => ({default: () => null}));
const docxCallbacks = vi.hoisted(() => ({ pending: null }));
vi.mock('./OnlineDocxEditor', () => ({default: ({onSelect}) => <><button onClick={() => onSelect('docx-version')}>Select synthetic DOCX</button><button onClick={() => { docxCallbacks.pending = () => onSelect('stale-docx'); }}>Begin delayed DOCX selection</button></>}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('ignores a late TXT save completion after a replacement DOCX is selected', async () => {
  const item = {manuscript_id: 12, title: 'Race draft', abstract: 'Synthetic', status: 'draft', has_pdf: true, file_type: 'txt', created_at: '2026-01-01'};
  const json = value => ({ok: true, headers: new Headers({'content-type': 'application/json'}), json: async () => value});
  let finishReload; let txtReads = 0;
  const fetchMock = vi.fn((url, options = {}) => {
    if (url.endsWith('/online-text') && options.method === 'POST') return Promise.resolve(json({}));
    if (url.endsWith('/online-text')) {
      if (++txtReads === 1) return Promise.resolve(json({content: 'original', version: 0, history: []}));
      return new Promise(resolve => { finishReload = resolve; });
    }
    if (url.endsWith('/upload')) return Promise.resolve(json({}));
    if (url.endsWith('/manuscripts/12')) return Promise.resolve(json({...item, file_type: 'docx'}));
    if (url.includes('/submit')) return Promise.resolve(json({}));
    if (url.includes('/notes')) return Promise.resolve(json([]));
    return Promise.resolve(json([item]));
  });
  vi.stubGlobal('fetch', fetchMock); vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<AuthorDashboard user={{name: 'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Race draft')).closest('.manuscript-card')).getByRole('button', {name: 'Open manuscript'}));
  const card = screen.getByText('Race draft').closest('.manuscript-card');
  fireEvent.click(within(card).getByRole('button', {name: 'Edit document (TXT)'}));
  fireEvent.change(await screen.findByLabelText('Document text'), {target: {value: 'edited'}});
  fireEvent.click(screen.getByRole('button', {name: 'Save Version'}));
  await waitFor(() => expect(finishReload).toBeTypeOf('function'));
  fireEvent.change(card.querySelector('input[type=file]'), {target: {files: [new File(['docx'], 'replacement.docx')]}});
  fireEvent.click(await screen.findByRole('button', {name: 'Select synthetic DOCX'}));
  await act(async () => { finishReload(json({content: 'edited', version: 7, history: [{is_current: true}]})); });
  fireEvent.click(within(card).getByRole('button', {name: 'Submit Manuscript'}));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.includes('/submit?selected_docx_version=docx-version'))).toBe(true));
  expect(fetchMock.mock.calls.some(([url]) => url.includes('expected_online_version=7'))).toBe(false);
});


it('ignores a late DOCX selection after replacing the source with TXT', async () => {
  const item = {manuscript_id: 12, title: 'DOCX race', abstract: 'Synthetic', status: 'draft', has_pdf: true, file_type: 'docx', created_at: '2026-01-01'};
  const json = value => ({ok: true, headers: new Headers({'content-type': 'application/json'}), json: async () => value});
  const fetchMock = vi.fn((url) => {
    if (url.endsWith('/online-text')) return Promise.resolve(json({content: 'txt', version: 4, history: [{is_current: true}]}));
    if (url.endsWith('/upload')) return Promise.resolve(json({}));
    if (url.endsWith('/manuscripts/12')) return Promise.resolve(json({...item, file_type: 'txt'}));
    if (url.includes('/submit')) return Promise.resolve(json({}));
    if (url.includes('/notes')) return Promise.resolve(json([]));
    return Promise.resolve(json([item]));
  });
  vi.stubGlobal('fetch', fetchMock); vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<AuthorDashboard user={{name: 'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('DOCX race')).closest('.manuscript-card')).getByRole('button', {name: 'Open manuscript'}));
  const card = screen.getByText('DOCX race').closest('.manuscript-card');
  fireEvent.click(within(card).getByRole('button', {name: 'Begin delayed DOCX selection'}));
  fireEvent.change(card.querySelector('input[type=file]'), {target: {files: [new File(['txt'], 'replacement.txt')]}});
  fireEvent.click(await screen.findByRole('button', {name: 'Edit document (TXT)'}));
  await screen.findByLabelText('Document text');
  await act(async () => { docxCallbacks.pending(); });
  fireEvent.click(within(card).getByRole('button', {name: 'Submit Manuscript'}));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.includes('/submit?expected_online_version=4'))).toBe(true));
  expect(fetchMock.mock.calls.some(([url]) => url.includes('selected_docx_version=stale-docx'))).toBe(false);
});

it('preserves the selected DOCX after a failed replacement upload', async () => {
  const item = {manuscript_id: 12, title: 'Failed upload', abstract: 'Synthetic', status: 'draft', has_pdf: true, file_type: 'docx', created_at: '2026-01-01'};
  const json = value => ({ok: true, headers: new Headers({'content-type': 'application/json'}), json: async () => value});
  const fetchMock = vi.fn(url => {
    if (url.includes('/notes')) return Promise.resolve(json([]));
    if (url.endsWith('/upload')) return Promise.resolve({ok: false, headers: new Headers({'content-type': 'application/json'}), json: async () => ({detail: 'Upload failed'})});
    return Promise.resolve(json(url.includes('/submit') ? {} : [item]));
  });
  vi.stubGlobal('fetch', fetchMock); vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<AuthorDashboard user={{name: 'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Failed upload')).closest('.manuscript-card')).getByRole('button', {name: 'Open manuscript'}));
  const card = screen.getByText('Failed upload').closest('.manuscript-card');
  fireEvent.click(within(card).getByRole('button', {name: 'Select synthetic DOCX'}));
  fireEvent.change(card.querySelector('input[type=file]'), {target: {files: [new File(['txt'], 'replacement.txt')]}});
  await screen.findByText('Upload failed');
  fireEvent.click(within(card).getByRole('button', {name: 'Submit Manuscript'}));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.includes('/submit?selected_docx_version=docx-version'))).toBe(true));
});

it('uses the replacement file for revision submission without a stale DOCX query', async () => {
  const item = {manuscript_id: 12, title: 'Revision draft', abstract: 'Synthetic', status: 'revision_required', has_pdf: true, file_type: 'docx', created_at: '2026-01-01'};
  const json = value => ({ok: true, headers: new Headers({'content-type': 'application/json'}), json: async () => value});
  const fetchMock = vi.fn(url => Promise.resolve(json(url.endsWith('/upload') || url.includes('/resubmit') ? {} : [item])));
  vi.stubGlobal('fetch', fetchMock);
  render(<AuthorDashboard user={{name: 'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Revision draft')).closest('.manuscript-card')).getByRole('button', {name: 'Open manuscript'}));
  const card = screen.getByText('Revision draft').closest('.manuscript-card');
  fireEvent.click(within(card).getByRole('button', {name: 'Select synthetic DOCX'}));
  fireEvent.click(within(card).getByRole('button', {name: 'Revise Manuscript'}));
  fireEvent.change(screen.getByLabelText(/Revised manuscript file/), {target: {files: [new File(['replacement'], 'replacement.docx')]}});
  fireEvent.submit(screen.getByRole('button', {name: 'Resubmit Manuscript'}).closest('form'));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/manuscripts/12/resubmit'))).toBe(true));
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/upload'))).toHaveLength(1);
  expect(fetchMock.mock.calls.some(([url]) => url.includes('/resubmit?selected_docx_version='))).toBe(false);
});

it.each(['invalid', 'failed'])('preserves selected DOCX after %s revision replacement', async failure => {
  const item = {manuscript_id: 12, title: 'Revision preservation', abstract: 'Synthetic', status: 'revision_required', has_pdf: true, file_type: 'docx', created_at: '2026-01-01'};
  const json = value => ({ok: true, headers: new Headers({'content-type': 'application/json'}), json: async () => value});
  const fetchMock = vi.fn(url => url.endsWith('/upload') ? Promise.resolve({ok:false, headers:new Headers({'content-type':'application/json'}), json:async()=>({detail:'Synthetic failure'})}) : Promise.resolve(json(url.includes('/resubmit') ? {} : [item])));
  vi.stubGlobal('fetch', fetchMock);
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Revision preservation')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const card=screen.getByText('Revision preservation').closest('.manuscript-card');
  fireEvent.click(within(card).getByRole('button',{name:'Select synthetic DOCX'}));
  fireEvent.click(within(card).getByRole('button',{name:'Revise Manuscript'}));
  const input=screen.getByLabelText(/Revised manuscript file/);
  fireEvent.change(input,{target:{files:[new File(['data'],failure === 'invalid' ? 'bad.xyz' : 'replacement.docx')]}});
  fireEvent.submit(screen.getByRole('button',{name:'Resubmit Manuscript'}).closest('form'));
  await screen.findByText(failure === 'invalid' ? 'Only PDF, DOCX, DOC, and TXT files are allowed.' : 'Synthetic failure');
  expect(fetchMock.mock.calls.some(([url])=>url.includes('/resubmit'))).toBe(false);
  fireEvent.change(input,{target:{files:[]}});
  fireEvent.submit(screen.getByRole('button',{name:'Resubmit Manuscript'}).closest('form'));
  await waitFor(()=>expect(fetchMock.mock.calls.some(([url])=>url.includes('/resubmit?selected_docx_version=docx-version'))).toBe(true));
});

it('uses the selected DOCX for initial resubmission', async () => {
  const item={manuscript_id:12,title:'Initial revision',abstract:'Synthetic',status:'initial_revision_required',has_pdf:true,file_type:'docx',created_at:'2026-01-01'};
  const json=value=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>value});
  const fetchMock=vi.fn(url=>Promise.resolve(json(url.includes('/initial-resubmit')?{}:[item])));
  vi.stubGlobal('fetch',fetchMock);
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Initial revision')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const card=screen.getByText('Initial revision').closest('.manuscript-card');
  fireEvent.click(within(card).getByRole('button',{name:'Select synthetic DOCX'}));
  fireEvent.click(within(card).getByRole('button',{name:'Submit selected DOCX revision'}));
  await waitFor(()=>expect(fetchMock.mock.calls.some(([url])=>url.includes('/initial-resubmit?selected_docx_version=docx-version'))).toBe(true));
});

it('keeps online selections isolated between manuscripts', async () => {
  const items=[{manuscript_id:12,title:'DOCX manuscript',file_type:'docx'},{manuscript_id:13,title:'TXT manuscript',file_type:'txt'}].map(v=>({...v,abstract:'Synthetic',status:'draft',has_pdf:true,created_at:'2026-01-01'}));
  const json=value=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>value});
  const fetchMock=vi.fn(url=>Promise.resolve(json(url.endsWith('/online-text')?{content:'txt',version:4,history:[{is_current:true}]}:url.includes('/submit')?{}:url.includes('/notes')?[]:items)));
  vi.stubGlobal('fetch',fetchMock);vi.spyOn(window,'confirm').mockReturnValue(true);
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('DOCX manuscript')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByRole('button',{name:'Select synthetic DOCX'}));
  fireEvent.click(screen.getByRole('button',{name:'Back to Manuscripts'}));
  fireEvent.click(within(screen.getByText('TXT manuscript').closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByRole('button',{name:'Edit document (TXT)'}));
  await screen.findByLabelText('Document text');
  fireEvent.click(screen.getByRole('button',{name:'Back to Manuscripts'}));
  fireEvent.click(within(screen.getByText('DOCX manuscript').closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByRole('button',{name:'Submit Manuscript'}));
  await waitFor(()=>expect(fetchMock.mock.calls.some(([url])=>url.includes('/manuscripts/12/submit?selected_docx_version=docx-version'))).toBe(true));
});
