import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within,waitFor} from '@testing-library/react';
import AuthorDashboard from './AuthorDashboard';
vi.mock('./ManuscriptProgress',()=>({default:()=>null}));
vi.mock('./NotesPanel',()=>({default:()=>null}));
vi.mock('./InitialEditingPanel',()=>({default:()=>null}));
vi.mock('./FinalEditingPanel',()=>({default:()=>null}));
vi.mock('./FormattingPanel',()=>({default:()=>null}));
vi.mock('./AuthorAgreementPanel',()=>({default:()=>null}));
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
function setup(fail=false){
 let item={manuscript_id:7,title:'Original title',abstract:'Original abstract',status:'draft',created_at:'2026-01-01',has_pdf:false};
 const requests=[];
 vi.stubGlobal('crypto',{subtle:{digest:async()=>new Uint8Array(32).buffer}});
 vi.stubGlobal('fetch',vi.fn(async(url,options={})=>{
  if(options.method==='PATCH') {requests.push(JSON.parse(options.body));if(fail)return {ok:false,headers:new Headers({'content-type':'application/json'}),json:async()=>({detail:'This field changed elsewhere. Reload before saving.'})};item={...item,...JSON.parse(options.body)};return {ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>item};}
  return {ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>String(url).includes('/notes')?[]:[item]};
 }));
 render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic"/>);return requests;
}
it('saves one field while preserving another unsaved field',async()=>{
 const requests=setup();const card=(await screen.findByText('Original title')).closest('.manuscript-card');fireEvent.click(within(card).getByRole('button',{name:'Open manuscript'}));
 fireEvent.click(screen.getByRole('button',{name:'Edit Title'}));fireEvent.click(screen.getByRole('button',{name:'Edit Abstract'}));
 fireEvent.change(screen.getByLabelText('Title'),{target:{value:'New title'}});fireEvent.change(screen.getByLabelText('Abstract'),{target:{value:'Unsaved abstract'}});
 fireEvent.click(screen.getByRole('button',{name:'Save Title'}));
 await waitFor(()=>expect(requests).toEqual([{title:'New title'}]));
 await waitFor(()=>expect(screen.getByLabelText('Abstract').value).toBe('Unsaved abstract'));
 fireEvent.click(screen.getByRole('button',{name:'Save Abstract'}));
 await waitFor(()=>expect(requests).toEqual([{title:'New title'},{abstract:'Unsaved abstract'}]));
});
it('retains an unsaved field after a stale conflict and permits cancellation',async()=>{
 setup(true);const card=(await screen.findByText('Original title')).closest('.manuscript-card');fireEvent.click(within(card).getByRole('button',{name:'Open manuscript'}));
 fireEvent.click(screen.getByRole('button',{name:'Edit Title'}));fireEvent.change(screen.getByLabelText('Title'),{target:{value:'Unsaved'}});fireEvent.click(screen.getByRole('button',{name:'Save Title'}));
 expect(await screen.findByText(/This field changed elsewhere/)).toBeTruthy();expect(screen.getByLabelText('Title').value).toBe('Unsaved');
 fireEvent.click(screen.getByRole('button',{name:'Cancel Title'}));expect(screen.queryByLabelText('Title')).toBeNull();
});
it('keeps field loading and failures independent during concurrent saves',async()=>{
 let item={manuscript_id:7,title:'Original title',abstract:'Original abstract',status:'draft',created_at:'2026-01-01',has_pdf:false};
 const pending={};const patches=[];
 vi.stubGlobal('crypto',{subtle:{digest:async()=>new Uint8Array(32).buffer}});
 vi.stubGlobal('fetch',vi.fn(async(url,options={})=>{
  if(options.method==='PATCH') {const body=JSON.parse(options.body);const field=Object.keys(body)[0];patches.push(field);return new Promise(resolve=>{pending[field]=()=>{if(field==='title')resolve({ok:false,headers:new Headers({'content-type':'application/json'}),json:async()=>({detail:'Title conflict'})});else {item={...item,...body};resolve({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>item});}}});}
  return {ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>[item]};
 }));
 render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic"/>);
 fireEvent.click(within((await screen.findByText('Original title')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
 fireEvent.click(screen.getByRole('button',{name:'Edit Title'}));fireEvent.click(screen.getByRole('button',{name:'Edit Abstract'}));
 fireEvent.change(screen.getByLabelText('Title'),{target:{value:'Unsaved title'}});fireEvent.change(screen.getByLabelText('Abstract'),{target:{value:'Saved abstract'}});
 fireEvent.click(screen.getByRole('button',{name:'Save Title'}));
 await waitFor(()=>expect(patches).toEqual(['title']));
 expect(screen.getByRole('button',{name:'Saving Title...'}).disabled).toBe(true);
 expect(screen.getByRole('button',{name:'Save Abstract'}).disabled).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'Save Abstract'}));
 await waitFor(()=>expect(patches).toEqual(['title','abstract']));
 fireEvent.submit(screen.getByLabelText('Title').closest('form'));expect(patches).toEqual(['title','abstract']);
 pending.title();expect(await screen.findByText('Title conflict')).toBeTruthy();
 expect(screen.getByLabelText('Title').value).toBe('Unsaved title');
 expect(screen.getByRole('button',{name:'Saving Abstract...'}).disabled).toBe(true);
 pending.abstract();await waitFor(()=>expect(screen.queryByLabelText('Abstract')).toBeNull());
 expect(screen.getByText('Title conflict')).toBeTruthy();expect(screen.getByLabelText('Title').value).toBe('Unsaved title');
});
