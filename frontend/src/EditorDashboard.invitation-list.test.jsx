import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, within} from '@testing-library/react';
vi.mock('./NotificationBell',()=>({default:()=>null}));
vi.mock('./InitialEditingPanel',()=>({default:({manuscriptId})=><div>Initial invitation workspace {manuscriptId}</div>}));
vi.mock('./FinalEditingPanel',()=>({default:({manuscriptId})=><div>Final invitation workspace {manuscriptId}</div>}));
vi.mock('./DocumentDistribution',()=>({EditorReceivedDocuments:()=>null}));
import EditorDashboard from './EditorDashboard';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
it('shows pending invitations in the single manuscript list and opens only their invitation workspace',async()=>{
 const data={
  '/manuscripts/dashboard':[{manuscript_id:1,title:'Accessible paper',status:'submitted'}],
  '/manuscripts/dashboard/summary':{},'/formatting/my':[],
  '/eic/initial-editing/my':[{manuscript_id:2,title:'Pending initial',status:'initial_editor_invited',invitation:{status:'pending'}}],
  '/final-workflow/my':[{manuscript_id:3,title:'Pending final',status:'pending',manuscript_status:'final_editing'}],
 };
 vi.stubGlobal('fetch',vi.fn(async url=>{
  const path=String(url).replace(/^\/api/,'');
  if(Object.hasOwn(data,path))return {ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data[path]};
  return {ok:false,status:404,headers:new Headers({'content-type':'application/json'}),json:async()=>({})};
 }));
 render(<EditorDashboard user={{user_id:9,name:'Synthetic'}} token="synthetic" section="manuscripts" onSectionChange={()=>{}} />);
 expect(await screen.findByRole('heading',{name:'All Manuscripts'})).toBeTruthy();
 expect(await screen.findByRole('heading',{name:'Pending initial'})).toBeTruthy();
 expect(screen.getByRole('heading',{name:'Pending final'})).toBeTruthy();
 expect(screen.queryByText(/invitation workspace/)).toBeNull();
 fireEvent.click(within(screen.getByRole('heading',{name:'Pending initial'}).closest('.editor-card')).getByRole('button',{name:'Open manuscript'}));
 expect(screen.getByText('Initial invitation workspace 2')).toBeTruthy();
 expect(screen.queryByText('Final invitation workspace 2')).toBeNull();
 expect(screen.queryByText('Private Notes')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
 fireEvent.click(within(screen.getByRole('heading',{name:'Pending final'}).closest('.editor-card')).getByRole('button',{name:'Open manuscript'}));
 expect(screen.getByText('Final invitation workspace 3')).toBeTruthy();
 expect(screen.queryByText('Private Notes')).toBeNull();
});
