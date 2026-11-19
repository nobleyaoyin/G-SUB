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
it('retains and enables the same download control after a first upload', async () => {
  const item={manuscript_id:12,title:'Empty synthetic draft',abstract:'Synthetic',status:'draft',has_pdf:false,created_at:'2026-01-01'};
  const json=value=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>value});
  vi.stubGlobal('fetch',vi.fn(url=>Promise.resolve(json(url.includes('/notes') ? [] : url.endsWith('/manuscripts/12') ? {...item,has_pdf:true,file_type:'pdf'} : url.endsWith('/upload') ? {} : [item]))));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  const list=(await screen.findByText('Empty synthetic draft')).closest('.manuscript-card');
  fireEvent.click(within(list).getByRole('button',{name:'Open manuscript'}));
  const card=screen.getByText('Empty synthetic draft').closest('.manuscript-card');
  const download=within(card).getByRole('button',{name:'Download File'});
  expect(download.disabled).toBe(true);
  fireEvent.change(card.querySelector('input[type=file]'),{target:{files:[new File(['synthetic'],'sample.pdf')]}});
  await waitFor(()=>expect(download.disabled).toBe(false));
  expect(within(card).getByRole('button',{name:'Download File'})).toBe(download);
});

it('does not show upload progress for an invalid file or send a request', async () => {
  const item={manuscript_id:12,title:'Invalid synthetic draft',abstract:'Synthetic',status:'draft',has_pdf:false,created_at:'2026-01-01'};
  const fetchMock=vi.fn(async(url)=>({
    ok:true,
    headers:new Headers({'content-type':'application/json'}),
    json:async()=>url.includes('/notes') ? [] : [item]
  }));
  vi.stubGlobal('fetch',fetchMock);
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  const list=(await screen.findByText('Invalid synthetic draft')).closest('.manuscript-card');
  fireEvent.click(within(list).getByRole('button',{name:'Open manuscript'}));
  const card=screen.getByText('Invalid synthetic draft').closest('.manuscript-card');
  const button=within(card).getByRole('button',{name:'Upload File'});
  const labels=[];
  const observer=new MutationObserver(()=>labels.push(button.textContent.trim()));
  observer.observe(button,{childList:true,characterData:true,subtree:true});
  fireEvent.change(card.querySelector('input[type=file]'),{target:{files:[new File(['synthetic'],'invalid.xyz')]}});
  await screen.findByText('Only PDF, DOCX, DOC, and TXT files are allowed.');
  await waitFor(()=>expect(button.disabled).toBe(false));
  observer.disconnect();
  expect(labels).not.toContain('Uploading...');
  expect(fetchMock.mock.calls.some(([url])=>url.endsWith('/upload'))).toBe(false);
});
