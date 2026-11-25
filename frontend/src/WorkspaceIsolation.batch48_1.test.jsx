import {afterEach, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen} from '@testing-library/react';
import OnlineDocumentEditor from './OnlineDocumentEditor';
import NotesPanel from './NotesPanel';
import GeneralCommentsPanel from './GeneralCommentsPanel';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
it('clears the loaded document during an A to B switch', async () => {
  const pending=[]; vi.stubGlobal('fetch',vi.fn(()=>new Promise(resolve=>pending.push(resolve))));
  const view=render(<OnlineDocumentEditor manuscriptId={1} token="synthetic" />);
  fireEvent.click(screen.getByRole('button',{name:'Edit document (TXT)'}));
  await act(async()=>pending[0]({ok:true,json:async()=>({content:'Document A',version:'a',history:[]})}));
  expect(screen.getByLabelText('Document text').value).toBe('Document A');
  view.rerender(<OnlineDocumentEditor manuscriptId={2} token="synthetic" />);
  expect(screen.queryByDisplayValue('Document A')).toBeNull();
  await act(async()=>pending[1]({ok:true,json:async()=>({content:'Document B',version:'b',history:[]})}));
  expect(screen.getByLabelText('Document text').value).toBe('Document B');
});
it('does not hand an old selected draft to a new manuscript', async () => {
  const calls=[]; const selected=vi.fn();
  vi.stubGlobal('fetch',vi.fn(()=>new Promise(resolve=>calls.push(resolve))));
  const view=render(<OnlineDocumentEditor manuscriptId={1} token="synthetic" onUseSaved={selected} />);
  fireEvent.click(screen.getByRole('button',{name:'Edit document (TXT)'}));
  await act(async()=>calls[0]({ok:true,json:async()=>({content:'A',version:'a',history:[{id:1,number:1}]})}));
  fireEvent.click(screen.getByRole('button',{name:'Use saved draft'}));
  view.rerender(<OnlineDocumentEditor manuscriptId={2} token="synthetic" onUseSaved={selected} />);
  await act(async()=>calls[1]({ok:true,json:async()=>({content:'A',version:'a',history:[]})}));
  expect(selected).not.toHaveBeenCalled();
});
for (const [name,Component,record] of [
  ['notes',NotesPanel,content=>({note_id:1,content,created_at:'2026-01-01T00:00:00Z'})],
  ['comments',GeneralCommentsPanel,content=>({comment_id:1,content,author_name:'Synthetic',created_at:'2026-01-01T00:00:00Z'})],
]) it(`${name} ignore delayed A after A → B → A`, async () => {
  const calls=[]; vi.stubGlobal('fetch',vi.fn(()=>new Promise(resolve=>calls.push(resolve))));
  const view=render(<Component manuscriptId={1} token="synthetic" />);
  view.rerender(<Component manuscriptId={2} token="synthetic" />);
  await act(async()=>calls[1]({ok:true,status:200,json:async()=>[record('Current B')]}));
  expect(screen.getByText('Current B')).toBeTruthy();
  view.rerender(<Component manuscriptId={1} token="synthetic" />);
  await act(async()=>calls[2]({ok:true,status:200,json:async()=>[record('Current A')]}));
  await act(async()=>calls[0]({ok:true,status:200,json:async()=>[record('Old A')]}));
  expect(screen.getByText('Current A')).toBeTruthy(); expect(screen.queryByText('Current B')).toBeNull(); expect(screen.queryByText('Old A')).toBeNull();
});

it('does not initiate a formatter download from A after switching to B, while B can download', async () => {
  const {default:FormattingPanel}=await import('./FormattingPanel');
  let finishA;
  const items=[1,2].map(id=>({manuscript_id:id,title:`Paper ${id}`,status:'formatting',invitations:[{invitation_id:id,status:'accepted'}],submissions:[]}));
  const headers=new Headers({'content-type':'application/pdf'});
  vi.stubGlobal('fetch',vi.fn(url=>String(url).includes('/invitations/1/input') ? new Promise(resolve=>{finishA=resolve;})
    : String(url).includes('/invitations/2/input') ? Promise.resolve({ok:true,headers,blob:async()=>new Blob(['B'])})
    : Promise.resolve({ok:true,json:async()=>String(url).endsWith('/progress') ? {manuscript_id:1,stages:[]} : items})));
  const create=vi.fn(()=> 'blob:synthetic'); const revoke=vi.fn();
  vi.stubGlobal('URL',{createObjectURL:create,revokeObjectURL:revoke});
  const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
  render(<FormattingPanel role="formatter" token="synthetic" />);
  fireEvent.click((await screen.findAllByRole('button',{name:'Open manuscript'}))[0]);
  fireEvent.click(await screen.findByRole('button',{name:'Download approved final edit'}));
  fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
  fireEvent.click(screen.getAllByRole('button',{name:'Open manuscript'})[1]);
  await act(async()=>finishA({ok:true,headers,blob:async()=>new Blob(['A'])}));
  expect(create).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Download approved final edit'}));
  await act(async()=>{});
  expect(create).toHaveBeenCalledTimes(1);expect(click).toHaveBeenCalledTimes(1);
  click.mockRestore();
});
