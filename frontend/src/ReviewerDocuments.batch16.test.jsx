import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import ReviewerDashboard from './ReviewerDashboard';
vi.mock('./ManuscriptProgress',()=>({default:()=>null}));
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
it.each([1,2,3,12])('shows assignment-specific round %s and distinguishes review from attachment',async round=>{
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>url.endsWith('/assignments/my')?[{assignment_id:8,manuscript_id:9,review_round:round,status:'assigned',invitation_status:'accepted',review_file_available:true}]:[]})));
 render(<ReviewerDashboard user={{user_id:1,name:'Synthetic'}} token="synthetic" />);
 fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
 expect(screen.getByRole('heading',{name:`Review documents · Round ${round}`})).toBeTruthy();
 expect(screen.getByText(/Review comments and recommendations are submitted separately/)).toBeTruthy();
 expect(screen.getByRole('region',{name:'Your reviewed documents'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'Download Review File'})).toBeTruthy();
});
