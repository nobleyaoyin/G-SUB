import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import InitialEditingPanel from './InitialEditingPanel';
import FinalEditingPanel from './FinalEditingPanel';
import FormattingPanel from './FormattingPanel';
import ReviewerDashboard from './ReviewerDashboard';
vi.mock('./OnlineDocumentEditor', () => ({default: () => null}));
vi.mock('./OnlineDocxEditor', () => ({default: () => null}));
vi.mock('./NotificationBell', () => ({default: () => null}));
vi.mock('./ReviewerProfilePanel', () => ({default: () => null}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const cases = [
  ['initial', InitialEditingPanel, {manuscript_id:7, title:'Synthetic title', status:'initial_editing', invitation:{status:'accepted', editor:'Synthetic'}, submissions:[]}, 'Submit initial-editing document'],
  ['final', FinalEditingPanel, {manuscript_id:7, title:'Synthetic title', status:'accepted', manuscript_status:'final_editing', invitation_id:5, submissions:[]}, 'Submit final editing document'],
];
for (const [name, Component, item, submit] of cases) {
  it(`${name} retains a standalone heading and suppresses embedded titles while preserving the form`, async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ok:true, json:async()=>[item]})));
    const {rerender} = render(<Component role="editor" token="synthetic" onChanged={async()=>{}} />);
    expect(await screen.findByRole('heading', {name:'#7 Synthetic title'})).toBeTruthy();
    fireEvent.click(screen.getByText(/editor invitation information/i));
    expect(screen.getAllByText(/Synthetic title/)).toHaveLength(1);
    expect(screen.getByLabelText('Editing comments')).toBeTruthy();
    expect(screen.getByRole('button',{name:submit})).toBeTruthy();
    rerender(<Component role="editor" token="synthetic" manuscriptId={7} onChanged={async()=>{}} />);
    expect(screen.queryByRole('heading',{name:'#7 Synthetic title'})).toBeNull();
    expect(screen.queryByText(/Synthetic title/)).toBeNull();
    expect(await screen.findByLabelText('Editing comments')).toBeTruthy();
    expect(screen.getByRole('button',{name:submit})).toBeTruthy();
  });
  it(`${name} standalone uses the manuscript ID if a title is missing`, async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ok:true, json:async()=>[{...item,title:null}]})));
    render(<Component role="editor" token="synthetic" onChanged={async()=>{}} />);
    expect(await screen.findByRole('heading',{name:'Manuscript #7'})).toBeTruthy();
  });
}
it('formatter keeps the title in standalone list and selected view and omits it when embedded', async () => {
  const item={manuscript_id:7,title:'Synthetic title',status:'formatting',invitations:[{invitation_id:5,status:'accepted'}],submissions:[]};
  vi.stubGlobal('fetch', vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/progress') ? {manuscript_id:7,stages:[]} : [item]})));
  const {unmount}=render(<FormattingPanel role="formatter" token="synthetic" />);
  expect(await screen.findByRole('heading',{name:'#7 Synthetic title'})).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Open manuscript'}));
  expect(screen.getByRole('heading',{name:'Synthetic title'})).toBeTruthy();
  expect(screen.getByText('Manuscript #7')).toBeTruthy();
  expect(screen.getByRole('button',{name:'Download approved final edit'})).toBeTruthy();
  unmount();
  render(<FormattingPanel role="editor" manuscriptId={7} token="synthetic" showProgress={false} />);
  expect(await screen.findByRole('button',{name:'Download approved final edit'})).toBeTruthy();
  expect(screen.queryByText('Synthetic title')).toBeNull();
});
it.each([['protected',null], ['permitted','Authorized synthetic title']])('reviewer %s title is displayed only when supplied by the assignment', async (_mode,title) => {
  const headers=new Headers({'content-type':'application/json'});
  const assignment={assignment_id:4,manuscript_id:3,review_round:1,status:'assigned',invitation_status:'accepted',manuscript_title:title};
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,headers,json:async()=>url.endsWith('/assignments/my') ? [assignment] : url.endsWith('/progress') ? {manuscript_id:3,title:'Hidden progress title',stages:[]} : {}})));
  render(<ReviewerDashboard user={{user_id:1,name:'Synthetic'}} token="synthetic" />);
  const label=title || 'Manuscript #3';
  expect(await screen.findByRole('heading',{name:label})).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Open manuscript'}));
  const workspace=(await screen.findByRole('heading',{name:label})).closest('[data-workspace=selected]');
  expect(within(workspace).getAllByRole('heading',{name:label})).toHaveLength(1);
  expect(within(workspace).queryByText('Hidden progress title')).toBeNull();
  expect(within(workspace).queryByText(/Author:/)).toBeNull();
  expect(within(workspace).getByLabelText(/Review Comments/)).toBeTruthy();
});
