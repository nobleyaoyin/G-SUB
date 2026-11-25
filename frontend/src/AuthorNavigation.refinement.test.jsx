import {useState} from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import AuthorDashboard from './AuthorDashboard';
vi.mock('./InitialEditingPanel',()=>({default:()=>null}));vi.mock('./AuthorAgreementPanel',()=>({default:()=>null}));
vi.mock('./FinalEditingPanel',()=>({default:()=>null}));vi.mock('./FormattingPanel',()=>({default:()=>null}));
vi.mock('./ManuscriptProgress',()=>({default:()=>null}));vi.mock('./ManuscriptTimeline',()=>({default:()=>null}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks()});
const items=[{manuscript_id:1,title:'Alpha draft',status:'draft',created_at:'2026-01-01'},{manuscript_id:2,title:'Beta submitted',status:'submitted',created_at:'2026-01-02'},{manuscript_id:3,title:'Gamma revision',status:'revision_required',created_at:'2026-01-03'},{manuscript_id:4,title:'Delta accepted',status:'accepted',created_at:'2026-01-04'}].map(x=>({...x,abstract:'Synthetic',has_pdf:false}));
function setup(){
 let notices=Array.from({length:6},(_,i)=>({notification_id:i+1,manuscript_id:1,notification_type:'editor_update',message:`Notice ${i+1}`,created_at:'2026-01-01T12:00:00Z',is_read:false}));
 const json=data=>({ok:true,status:200,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
 const request=vi.fn(async(url,options={})=>{const path=String(url);if(path.endsWith('/notifications/my'))return json(notices);if(path.endsWith('/notifications/unread-count'))return json({unread_count:notices.filter(n=>!n.is_read).length});if(options.method==='PATCH' && path.includes('/notifications/')){const id=Number(path.match(/notifications\/(\d+)\/read/)[1]);notices=notices.map(n=>n.notification_id===id?{...n,is_read:true}:n);return json({});}if(path.endsWith('/manuscripts/my'))return json(items);if(path.includes('/notes'))return json([]);return json([]);});
 vi.stubGlobal('fetch',request);
 function Harness(){const [section,setSection]=useState('dashboard');return <><nav aria-label="Test navigation"><button onClick={()=>setSection('dashboard')}>Dashboard</button><button onClick={()=>setSection('manuscripts')}>Manuscripts</button><button onClick={()=>setSection('notifications')}>Notifications page</button></nav><AuthorDashboard user={{name:'Synthetic Author',role:'author'}} token="synthetic" section={section} onSectionChange={setSection}/></>}
 render(<Harness/>);return {request};
}
it('shows actual counts and at most three recent manuscripts, with navigation and new draft',async()=>{
 setup();const overview=await screen.findByRole('region',{name:'Author overview'});await within(overview).findByText('Delta accepted');expect(within(overview).queryByText('Alpha draft')).toBeNull();expect(within(overview).getAllByRole('button',{name:'Open manuscript'})).toHaveLength(3);
 const stats=screen.getByLabelText('Manuscript statistics');expect(overview.contains(stats)).toBe(false);const disclosure=stats.querySelector('details');expect(disclosure.open).toBe(false);fireEvent.click(within(stats).getByText('Statistics'));expect(disclosure.open).toBe(true);expect(within(stats).getByText('4')).toBeTruthy();for(const label of ['Drafts','Submitted / in progress','Accepted','Revision required'])expect(within(stats).getByText(label).parentElement.querySelector('strong').textContent).toBe('1');expect(within(stats).getByText('Rejected').parentElement.querySelector('strong').textContent).toBe('0');fireEvent.click(within(stats).getByText('Statistics'));expect(disclosure.open).toBe(false);
 expect(within(overview).queryByText('Quick Actions')).toBeNull();fireEvent.click(within(overview).getByRole('button',{name:'View all manuscripts'}));expect(await screen.findByText('Alpha draft')).toBeTruthy();expect(screen.getByLabelText('Manuscript statistics').querySelector('details')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'+ New Submission'}));expect(screen.getByRole('heading',{name:'Manuscript submission'})).toBeTruthy();
});
it('searches, filters and sorts the complete manuscript list',async()=>{
 setup();await screen.findByText('Delta accepted');fireEvent.click(screen.getByRole('button',{name:'Manuscripts'}));fireEvent.change(screen.getByLabelText('Search manuscripts'),{target:{value:'2'}});expect(screen.getByText('Beta submitted')).toBeTruthy();expect(screen.queryByText('Alpha draft')).toBeNull();fireEvent.change(screen.getByLabelText('Search manuscripts'),{target:{value:''}});fireEvent.change(screen.getByLabelText('Main stage'),{target:{value:'Peer Review'}});fireEvent.change(screen.getByLabelText('Sub-stage'),{target:{value:'revision_required'}});expect(screen.getByText('Gamma revision')).toBeTruthy();expect(screen.queryByText('Beta submitted')).toBeNull();fireEvent.change(screen.getByLabelText('Main stage'),{target:{value:''}});fireEvent.change(screen.getByLabelText('Sort'),{target:{value:'title'}});expect([...document.querySelectorAll('.manuscript-card h3')].map(x=>x.textContent)).toEqual(['Alpha draft','Beta submitted','Delta accepted','Gamma revision']);
});
it('keeps the five-item bell and full notification center synchronized',async()=>{
 const {request}=setup();await screen.findByText('Delta accepted');fireEvent.click(screen.getByRole('button',{name:'Notifications'}));await screen.findByRole('button',{name:'Notice 1'});expect(screen.queryByRole('button',{name:'Notice 6'})).toBeNull();fireEvent.click(screen.getByRole('button',{name:'View All notifications'}));
 const center=await screen.findByRole('region',{name:'Notification center'});expect(within(center).getByText('Notice 6')).toBeTruthy();fireEvent.click(within(center).getAllByRole('button',{name:'Mark as read'})[0]);await waitFor(()=>expect(within(center).getAllByRole('button',{name:'Mark as read'})).toHaveLength(5));expect(document.querySelector('.notification-badge').textContent).toBe('5');fireEvent.click(within(center).getByRole('button',{name:'Mark all as read'}));await waitFor(()=>expect(within(center).queryAllByRole('button',{name:'Mark as read'})).toHaveLength(0));expect(request.mock.calls.filter(([,options])=>options?.method==='PATCH')).toHaveLength(6);fireEvent.click(within(center).getByRole('button',{name:'Unread'}));expect(within(center).getByText('No notifications in this view.')).toBeTruthy();fireEvent.click(within(center).getByRole('button',{name:'← Back'}));expect(await screen.findByText('Dashboard Overview')).toBeTruthy();
});
it('opens a recent manuscript and returns to the manuscript list',async()=>{
 setup();await screen.findByText('Delta accepted');fireEvent.click(screen.getAllByRole('button',{name:'Open manuscript'})[0]);
 expect(await screen.findByRole('heading',{name:'Delta accepted'})).toBeTruthy();expect(screen.queryByText('Dashboard Overview')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));expect(await screen.findByText('Alpha draft')).toBeTruthy();
});
it('closes the quick notification panel on outside click',async()=>{
 setup();await screen.findByText('Delta accepted');fireEvent.click(screen.getByRole('button',{name:'Notifications'}));await screen.findByRole('button',{name:'Notice 1'});
 fireEvent.pointerDown(document.body);expect(screen.queryByRole('button',{name:'Notice 1'})).toBeNull();
});
