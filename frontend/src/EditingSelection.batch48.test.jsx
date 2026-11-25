import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import InitialEditingPanel from './InitialEditingPanel';
import FinalEditingPanel from './FinalEditingPanel';
vi.mock('./OnlineDocumentEditor', () => ({default: () => null}));
vi.mock('./OnlineDocxEditor', () => ({default: () => null}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
for (const [name, Component, build] of [
  ['initial', InitialEditingPanel, (id,text)=>({manuscript_id:id,title:`Paper ${id}`,status:'initial_editing',invitation:{status:'accepted',editor:'Synthetic'},submissions:[{submission_id:id,status:'pending_author',comments:text}]})],
  ['final', FinalEditingPanel, (id,text)=>({manuscript_id:id,title:`Paper ${id}`,status:'accepted',manuscript_status:'final_editing',invitation_id:id,submissions:[{submission_id:id,status:'pending_author',comments:text}]})],
]) {
  it(`${name} ignores delayed A after B and a later return to A`, async () => {
    const pending=[];
    vi.stubGlobal('fetch',vi.fn(()=>new Promise(resolve=>pending.push(resolve))));
    const {rerender}=render(<Component role="editor" token="synthetic" manuscriptId={1} onChanged={async()=>{}} />);
    rerender(<Component role="editor" token="synthetic" manuscriptId={2} onChanged={async()=>{}} />);
    expect(pending).toHaveLength(2);
    await act(async()=>pending[1]({ok:true,json:async()=>[build(2,'Current B data')]}));
    expect(screen.getByText(/Current B data/)).toBeTruthy();
    rerender(<Component role="editor" token="synthetic" manuscriptId={1} onChanged={async()=>{}} />);
    expect(screen.queryByText(/Current B data/)).toBeNull();
    expect(pending).toHaveLength(3);
    await act(async()=>pending[2]({ok:true,json:async()=>[build(1,'New A data')]}));
    expect(screen.getByText(/New A data/)).toBeTruthy();
    await act(async()=>pending[0]({ok:true,json:async()=>[build(1,'Stale A data')]}));
    expect(screen.queryByText(/Stale A data/)).toBeNull();
    expect(screen.getByText(/New A data/)).toBeTruthy();
    expect(screen.queryByText(/Current B data/)).toBeNull();
  });
}

it('keeps the selected reviewer assignment and round when an earlier assignment response arrives late', async () => {
  const {default: ReviewerDashboard} = await import('./ReviewerDashboard');
  const headers = new Headers({'content-type':'application/json'});
  let finishDetails;
  vi.stubGlobal('fetch',vi.fn(url=>{
    if(url.endsWith('/assignments/my')) return Promise.resolve({ok:true,headers,json:async()=>[1,2].map(round=>({assignment_id:round,manuscript_id:7,review_round:round,status:'assigned',invitation_status:'accepted'}))});
    if(url.endsWith('/manuscripts/7')) return new Promise(resolve=>{finishDetails=resolve;});
    return Promise.resolve({ok:true,headers,json:async()=>({manuscript_id:7,stages:[]})});
  }));
  const {container}=render(<ReviewerDashboard user={{user_id:2,name:'Synthetic'}} token="synthetic" />);
  const first=await screen.findAllByRole('button',{name:'Open manuscript'});
  act(()=>first[0].click());
  act(()=>screen.getByRole('button',{name:'View manuscript details'}).click());
  act(()=>screen.getByRole('button',{name:'Back to manuscripts'}).click());
  act(()=>screen.getAllByRole('button',{name:'Open manuscript'})[1].click());
  expect(screen.getByRole('heading',{name:'Review documents · Round 2'})).toBeTruthy();
  await act(async()=>finishDetails({ok:true,headers,json:async()=>({manuscript_id:7,author_name:'Stale assignment detail'})}));
  expect(screen.queryByText(/Stale assignment detail/)).toBeNull();
  expect(container.querySelector('[data-workspace=selected]').getAttribute('data-review-round')).toBe('2');
});
