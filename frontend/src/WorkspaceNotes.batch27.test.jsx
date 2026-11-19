import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import NotesPanel from './NotesPanel';
import GeneralCommentsPanel from './GeneralCommentsPanel';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
const ok=data=>({ok:true,status:200,json:async()=>data});
for(const [name,Component,endpoint] of [['notes',NotesPanel,'notes'],['comments',GeneralCommentsPanel,'general-comments']]) {
 it(`${name} discards a late response from an old manuscript`,async()=>{
  let release;
  vi.stubGlobal('fetch',vi.fn(url=>String(url).includes('/1/')?new Promise(resolve=>{release=resolve}):Promise.resolve(ok(endpoint==='notes'?[{note_id:2,content:'Only B',updated_at:'2026-01-01'}]:[{comment_id:2,content:'Only B',author_name:'Staff',created_at:'2026-01-01'}]))));
  const {rerender}=render(<Component manuscriptId={1} token="synthetic"/>);
  await waitFor(()=>expect(release).toBeTypeOf('function'));
  rerender(<Component manuscriptId={2} token="synthetic"/>);
  expect(await screen.findByText('Only B')).toBeTruthy();
  release(ok(endpoint==='notes'?[{note_id:1,content:'Stale A',updated_at:'2026-01-01'}]:[{comment_id:1,content:'Stale A',author_name:'Staff',created_at:'2026-01-01'}]));
  await waitFor(()=>expect(screen.queryByText('Stale A')).toBeNull());
  expect(screen.getByText('Only B')).toBeTruthy();
 });
 it(`${name} keeps a failed submission visible and preserves its draft`,async()=>{
  vi.stubGlobal('fetch',vi.fn(async(_url,options={})=>options.method==='POST'?{ok:false,status:500,json:async()=>({detail:'Synthetic save failed'})}:ok([])));
  render(<details open><summary>Context</summary><Component manuscriptId={1} token="synthetic"/></details>);
  const details=screen.getByText('Context').parentElement;
  const textarea=screen.getByLabelText(endpoint==='notes'?'New note':'Add a general comment');
  fireEvent.change(textarea,{target:{value:'Unsaved draft'}});
  fireEvent.click(within(details).getByRole('button',{name:endpoint==='notes'?'Add Note':'Add Comment'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Synthetic save failed');
  details.open=false;fireEvent(details,new Event('toggle'));
  await waitFor(()=>expect(details.open).toBe(true));
  expect(textarea.value).toBe('Unsaved draft');
 });
}
for(const [name,Component,endpoint] of [['notes',NotesPanel,'notes'],['comments',GeneralCommentsPanel,'general-comments']]) {
 it(`${name} discards a response from an old authentication token`,async()=>{
  let release;
  vi.stubGlobal('fetch',vi.fn((_url,options)=>options.headers.Authorization==='Bearer old'?new Promise(resolve=>{release=resolve}):Promise.resolve(ok(endpoint==='notes'?[{note_id:2,content:'New account',updated_at:'2026-01-01'}]:[{comment_id:2,content:'New account',author_name:'Staff',created_at:'2026-01-01'}]))));
  const {rerender}=render(<Component manuscriptId={1} token="old"/>);
  await waitFor(()=>expect(release).toBeTypeOf('function'));
  rerender(<Component manuscriptId={1} token="new"/>);
  expect(await screen.findByText('New account')).toBeTruthy();
  release(ok(endpoint==='notes'?[{note_id:1,content:'Old account',updated_at:'2026-01-01'}]:[{comment_id:1,content:'Old account',author_name:'Staff',created_at:'2026-01-01'}]));
  await waitFor(()=>expect(screen.queryByText('Old account')).toBeNull());
 });
}
