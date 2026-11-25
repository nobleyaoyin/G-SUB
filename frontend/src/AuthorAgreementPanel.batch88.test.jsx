import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import AuthorAgreementPanel from './AuthorAgreementPanel';
vi.mock('./useReturnRefresh',()=>({default:()=>{}}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const prototype={agreement_id:1,manuscript_id:11,manuscript_title:'Synthetic manuscript',agreement_version:'placeholder-v1',agreement_text:'Synthetic prototype text',template_status:'prototype',status:'pending',manuscript_status:'awaiting_author_agreement',created_at:'2026-01-01T00:00:00Z'};
it('shows prototype, version, generated date and an idempotent response',async()=>{
 let status='pending';let resolveSave;
 const fetcher=vi.fn((url,options={})=>{
  if(options.method==='POST')return new Promise(resolve=>{resolveSave=()=>{status='accepted';resolve({ok:true,json:async()=>({status:'accepted',manuscript_status:'final_editing',responded_at:'2026-01-02T00:00:00Z'})});};});
  return Promise.resolve({ok:true,json:async()=>[{...prototype,status,manuscript_status:status==='pending'?'awaiting_author_agreement':'final_editing'}]});
 });
 vi.stubGlobal('fetch',fetcher);
 render(<AuthorAgreementPanel token="synthetic" manuscriptId={11} onChanged={()=>true}/>);
 expect(await screen.findByText('Synthetic manuscript')).toBeTruthy();
 expect(screen.getByText(/Prototype only/)).toBeTruthy();expect(screen.getByText('Template approval: Pending owner approval.')).toBeTruthy();expect(screen.getByText('placeholder-v1')).toBeTruthy();
 expect(screen.getByText(/Generated/)).toBeTruthy();expect(screen.getByText('Synthetic prototype text')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Accept Agreement'}));
 expect(screen.getByRole('button',{name:'Decline Agreement'}).disabled).toBe(true);
 resolveSave();
 await screen.findByText('Agreement response recorded: accepted.');
 await waitFor(()=>expect(screen.queryByRole('button',{name:'Accept Agreement'})).toBeNull());
 expect(fetcher.mock.calls.filter(([,opt])=>opt?.method==='POST')).toHaveLength(1);
});
it('shows declined state and safe loading failure',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[{...prototype,status:'declined',manuscript_status:'author_agreement_declined'}]})));
 const view=render(<AuthorAgreementPanel token="synthetic" manuscriptId={11}/>);
 expect(await screen.findByText(/Final editing is on hold/)).toBeTruthy();expect(screen.queryByRole('button',{name:'Accept Agreement'})).toBeNull();
 view.unmount();vi.stubGlobal('fetch',vi.fn(async()=>({ok:false})));
 render(<AuthorAgreementPanel token="synthetic" manuscriptId={11}/>);
 expect((await screen.findByRole('alert')).textContent).toContain('Could not load author agreements');
});
it('does not show an old account response after account switching',async()=>{
 let resolveOld;const old=new Promise(resolve=>{resolveOld=resolve;});
 vi.stubGlobal('fetch',vi.fn((_url,options)=>options.headers.Authorization==='Bearer old'?old:Promise.resolve({ok:true,json:async()=>[{...prototype,manuscript_title:'New account manuscript'}]})));
 const view=render(<AuthorAgreementPanel token="old" manuscriptId={11}/>);
 await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));
 view.rerender(<AuthorAgreementPanel token="new" manuscriptId={11}/>);
 expect(await screen.findByText('New account manuscript')).toBeTruthy();
 resolveOld({ok:true,json:async()=>[{...prototype,manuscript_title:'Old account manuscript'}]});
 await waitFor(()=>expect(screen.queryByText('Old account manuscript')).toBeNull());
});
it('does not invent a saved response from a malformed success body',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(_url,options={})=>options.method==='POST'?{ok:true,json:async()=>({})}:{ok:true,json:async()=>[prototype]}));
 render(<AuthorAgreementPanel token="synthetic" manuscriptId={11}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Accept Agreement'}));
 expect((await screen.findByRole('alert')).textContent).toContain('could not be verified');
 expect(screen.queryByText('Agreement response recorded: accepted.')).toBeNull();
});
it('submits a decline and displays the saved state',async()=>{
 let declined=false;
 const fetcher=vi.fn(async(_url,options={})=>{
  if(options.method==='POST'){
   expect(JSON.parse(options.body)).toEqual({decision:'decline',agreement_version:'placeholder-v1'});
   declined=true;return {ok:true,json:async()=>({status:'declined',manuscript_status:'author_agreement_declined'})};
  }
  return {ok:true,json:async()=>[{...prototype,status:declined?'declined':'pending',manuscript_status:declined?'author_agreement_declined':'awaiting_author_agreement'}]};
 });
 vi.stubGlobal('fetch',fetcher);
 render(<AuthorAgreementPanel token="synthetic" manuscriptId={11} onChanged={()=>true}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Decline Agreement'}));
 expect(await screen.findByText('Agreement response recorded: declined.')).toBeTruthy();
 expect(screen.getByText(/Final editing is on hold/)).toBeTruthy();
});
it('does not overwrite the selected manuscript with a delayed earlier response',async()=>{
 let resolveOld;let calls=0;const old=new Promise(resolve=>{resolveOld=resolve;});
 vi.stubGlobal('fetch',vi.fn(()=>{calls++;return calls===1?old:Promise.resolve({ok:true,json:async()=>[{...prototype,manuscript_id:22,manuscript_title:'Second manuscript'}]});}));
 const view=render(<AuthorAgreementPanel token="synthetic" manuscriptId={11}/>);
 await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));
 view.rerender(<AuthorAgreementPanel token="synthetic" manuscriptId={22}/>);
 expect(await screen.findByText('Second manuscript')).toBeTruthy();
 resolveOld({ok:true,json:async()=>[{...prototype,manuscript_title:'First manuscript'}]});
 await waitFor(()=>expect(screen.getByText('Second manuscript')).toBeTruthy());
 expect(screen.queryByText('First manuscript')).toBeNull();
});
