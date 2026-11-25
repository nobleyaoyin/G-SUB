import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import AuthorDashboard from './AuthorDashboard';
vi.mock('./NotificationBell', () => ({default: () => null}));
vi.mock('./InitialEditingPanel', () => ({default: () => null}));
vi.mock('./AuthorAgreementPanel', () => ({default: () => null}));
vi.mock('./FinalEditingPanel', () => ({default: () => null}));
vi.mock('./FormattingPanel', () => ({default: () => null}));
vi.mock('./ManuscriptProgress', () => ({default: () => null}));
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
it('enables the wizard download after the first upload', async () => {
  const item={manuscript_id:12,title:'Empty synthetic draft',abstract:'Synthetic',status:'draft',has_pdf:false,created_at:'2026-01-01'};
  const json=value=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>value});
  vi.stubGlobal('fetch',vi.fn(url=>Promise.resolve(json(url.includes('/notes') ? [] : url.endsWith('/manuscripts/12') ? {...item,has_pdf:true,file_type:'pdf'} : url.endsWith('/upload') ? {} : [item]))));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Empty synthetic draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  let card=screen.getByText('Empty synthetic draft').closest('.manuscript-card');
  expect(within(card).queryByRole('button',{name:'Download file'})).toBeNull();
  expect(within(card).queryByRole('button',{name:'Upload File'})).toBeNull();
  fireEvent.click(within(card).getByRole('button',{name:'Continue Process'}));
  fireEvent.change(screen.getByLabelText(/Select Manuscript File/),{target:{files:[new File(['synthetic'],'sample.pdf')]}});
  fireEvent.click(screen.getByRole('button',{name:'Upload File'}));
  await screen.findByRole('heading',{name:'Review Your Submission'});
  fireEvent.click(screen.getByRole('button',{name:'← Previous'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Download Current File'}).disabled).toBe(false));
});

it('rejects invalid wizard files before making an upload request', async () => {
  const item={manuscript_id:12,title:'Invalid synthetic draft',abstract:'Synthetic',status:'draft',has_pdf:false,created_at:'2026-01-01'};
  const fetchMock=vi.fn(async(url)=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>url.includes('/notes') ? [] : [item]}));
  vi.stubGlobal('fetch',fetchMock);
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Invalid synthetic draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByRole('button',{name:'Continue Process'}));
  fireEvent.change(screen.getByLabelText(/Select Manuscript File/),{target:{files:[new File(['synthetic'],'invalid.xyz')]}});
  await screen.findByText('Only PDF, DOCX, DOC, and TXT files are allowed.');
  expect(screen.getByRole('button',{name:'Upload File'}).disabled).toBe(true);
  expect(fetchMock.mock.calls.some(([url])=>url.endsWith('/upload'))).toBe(false);
});
