import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, within} from '@testing-library/react';

// Test-only hook instrumentation seeds an otherwise unreachable conflict; the
// production UI is not given an injection prop and is not changed by this test.
const seed = vi.hoisted(() => ({states: 0, refs: 0}));
vi.mock('react', async importOriginal => {
  const real = await importOriginal();
  return {...real,
    useState(initial) {
      if (initial && typeof initial === 'object' && !Array.isArray(initial) && Object.keys(initial).length === 0 && ++seed.states === 1) initial={12:'docx-version'};
      return real.useState(initial);
    },
    useRef(initial) {
      if (initial && typeof initial === 'object' && !Array.isArray(initial) && Object.keys(initial).length === 0 && ++seed.refs === 1) initial={12:'txt-version'};
      return real.useRef(initial);
    },
  };
});
vi.mock('./NotificationBell', () => ({default: () => null}));
vi.mock('./InitialEditingPanel', () => ({default: () => null}));
vi.mock('./AuthorAgreementPanel', () => ({default: () => null}));
vi.mock('./FinalEditingPanel', () => ({default: () => null}));
vi.mock('./FormattingPanel', () => ({default: () => null}));
vi.mock('./ManuscriptProgress', () => ({default: () => null}));
vi.mock('./OnlineDocxEditor', () => ({default: () => null}));
import AuthorDashboard from './AuthorDashboard';
beforeEach(()=>{seed.states=0;seed.refs=0});
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks()});

it.each(['draft','draft_upload','revision_required','initial_revision_required'])('rejects artificial conflicting selections before %s workflow requests',async stage=>{
  const item={manuscript_id:12,title:'Synthetic conflict',abstract:'Synthetic',status:stage==='draft_upload'?'draft':stage,has_pdf:true,file_type:'docx',created_at:'2026-01-01'};
  const fetchMock=vi.fn(async()=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>[item]}));
  vi.stubGlobal('fetch',fetchMock);const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic"/>);
  fireEvent.click(within((await screen.findByText('Synthetic conflict')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  if(stage==='draft'){
    fireEvent.click(screen.getByRole('button',{name:'Continue Process'}));
    fireEvent.click(screen.getByRole('button',{name:'Continue to Review'}));
    fireEvent.click(screen.getByRole('button',{name:'Submit Manuscript'}));
  }
  if(stage==='draft_upload'){
    fireEvent.click(screen.getByRole('button',{name:'Continue Process'}));
    fireEvent.change(screen.getByLabelText(/Select a Replacement File/),{target:{files:[new File(['x'],'replacement.docx')]}});
    fireEvent.click(screen.getByRole('button',{name:'Upload Replacement File'}));
  }
  if(stage==='revision_required'){
    fireEvent.click(screen.getByRole('button',{name:'Revise Editor Manuscript'}));
    fireEvent.change(screen.getByLabelText(/Revised manuscript file/),{target:{files:[new File(['x'],'replacement.docx')]}});
    fireEvent.submit(screen.getByRole('button',{name:'Resubmit Manuscript'}).closest('form'));
  }
  if(stage==='initial_revision_required')fireEvent.click(screen.getByRole('button',{name:'Submit selected DOCX revision'}));
  expect(await screen.findByText('Please select only one online draft version.')).toBeTruthy();
  expect(confirm).not.toHaveBeenCalled();
  expect(fetchMock.mock.calls.some(([url])=>/\/(upload|submit|resubmit|initial-resubmit)(\?|$)/.test(url))).toBe(false);
});
