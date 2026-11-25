import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import StageDialoguePanel from './StageDialoguePanel';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('previews the audience before opening and sending a thread',async()=>{
  const participants=[{role:'Author',name:'Synthetic Author'},{role:'Editor',name:'Synthetic Editor'}];
  const thread={thread_id:'a'.repeat(32),stage:'initial_editing',round_kind:'pre_review',review_round:null,participants};
  let messages=[];
  const fetcher=vi.fn(async(url,options={})=>({ok:true,json:async()=>{
    if(url.includes('audience-preview'))return {...thread};
    if(url.endsWith('/messages')){messages=[{message_id:'1',sender:'Synthetic Author',body:JSON.parse(options.body).body,created_at:'2026-11-21T09:32:14.123456+00:00'}];return {message_id:'1'};}
    if(url.endsWith('/threads') && options.method==='POST')return thread;
    if(url.endsWith('/threads'))return [];
    return {thread,messages};
  }}));
  vi.stubGlobal('fetch',fetcher);
  render(<StageDialoguePanel manuscriptId={9} token="synthetic"/>);
  fireEvent.click(screen.getByText('Stage Threads'));
  await screen.findByText('No available stage threads.');
  fireEvent.click(screen.getByRole('button',{name:'Preview audience'}));
  expect(await screen.findByText(/Visible to: Author: Synthetic Author/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Open stage thread'}));
  await screen.findByText('No messages yet.');
  const send=screen.getByRole('button',{name:'Send message'});
  expect(send.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Message'),{target:{value:'Synthetic message'}});
  fireEvent.click(screen.getByRole('button',{name:'Review audience before sending'}));
  await screen.findByText(/Will be visible to:/);
  expect(send.disabled).toBe(false);
  fireEvent.click(send);
  await waitFor(()=>expect(screen.getByText(/Synthetic message/)).toBeTruthy());
  expect(screen.getByText(/2026-11-21T09:32:14.123456\+00:00/)).toBeTruthy();
  expect(fetcher.mock.calls.filter(([url])=>url.endsWith('/messages'))).toHaveLength(1);
});
it('labels unavailable message timestamps without inventing a date',async()=>{
  const thread={thread_id:'a'.repeat(32),stage:'initial_editing',round_kind:'pre_review',participants:[]};
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/threads')?[thread]:{thread,messages:[{message_id:'1',sender:'Editor',body:'Synthetic note',created_at:'bad-date'}]}})));
  render(<StageDialoguePanel manuscriptId={9} token="synthetic"/>);
  fireEvent.click(screen.getByText('Stage Threads'));
  fireEvent.click(await screen.findByRole('button',{name:/initial editing.*Pre-review/i}));
  expect(await screen.findByText(/Unavailable/)).toBeTruthy();
});
it('shows a safe error when dialogue is unavailable',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,json:async()=>({detail:'Dialogue unavailable'})})));
  render(<StageDialoguePanel manuscriptId={9} token="synthetic"/>);
  fireEvent.click(screen.getByText('Stage Threads'));
  expect((await screen.findByRole('alert')).textContent).toContain('Dialogue unavailable');
  expect(screen.queryByRole('button',{name:'Send message'})).toBeNull();
});
it('does not render a delayed response from a previous manuscript',async()=>{
  let finishOld;
  const old=new Promise(resolve=>{finishOld=resolve;});
  const fetcher=vi.fn(url=>url.includes('/manuscripts/1/') ? old : Promise.resolve({ok:true,json:async()=>[]}));
  vi.stubGlobal('fetch',fetcher);
  const view=render(<StageDialoguePanel manuscriptId={1} token="synthetic"/>);
  fireEvent.click(screen.getByText('Stage Threads'));
  await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(1));
  view.rerender(<StageDialoguePanel manuscriptId={2} token="synthetic"/>);
  await waitFor(()=>expect(screen.getByText('Stage Threads').closest('details').open).toBe(false));
  fireEvent.click(screen.getByText('Stage Threads'));
  await screen.findByText('No available stage threads.');
  finishOld({ok:true,json:async()=>[{thread_id:'stale',stage:'initial_editing',round_kind:'pre_review',review_round:null,participants:[]}]});
  await waitFor(()=>expect(screen.queryByRole('button',{name:/initial editing.*Pre-review/i})).toBeNull());
});
