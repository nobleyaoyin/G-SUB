import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import InitialEditingPanel from './InitialEditingPanel';
import FinalEditingPanel from './FinalEditingPanel';
vi.mock('./OnlineDocumentEditor',()=>({default:()=>null}));
vi.mock('./OnlineDocxEditor',()=>({default:()=>null}));
afterEach(()=>{cleanup();vi.unstubAllGlobals()});

it.each(['pending','declined','accepted'])('initial invitation %s reveals only appropriate history',async status=>{
 const item={manuscript_id:7,title:'Synthetic title',invitation_abstract:'Author synthetic abstract',status:'initial_editor_invited',invitation:{invitation_id:3,status,editor:'Editor'},submissions:[{submission_id:5,status:'pending_author',comments:'Private edit'}]};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[item]})));
 render(<InitialEditingPanel role="editor" token="synthetic" onChanged={async()=>{}}/>);
 fireEvent.click(await screen.findByText('Initial editor invitation information'));
 expect(screen.getByText(/verified word and table counts/)).toBeTruthy();
 expect(screen.queryByText(/\/uploads\//)).toBeNull();
 expect(Boolean(screen.queryByText(/Private edit/))).toBe(status==='accepted');
 expect(Boolean(screen.queryByText(/Author synthetic abstract/))).toBe(status==='accepted');
});
it.each(['pending','declined','accepted'])('final invitation %s reveals only appropriate history',async status=>{
 const item={manuscript_id:7,title:'Synthetic title',invitation_abstract:'Author synthetic abstract',status,manuscript_status:'final_editing',invitation_id:4,submissions:[{submission_id:8,status:'pending_eic',comments:'Private final edit'}]};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[item]})));
 render(<FinalEditingPanel role="editor" token="synthetic" onChanged={async()=>{}}/>);
 fireEvent.click(await screen.findByText('Final editor invitation information'));
 expect(within(screen.getByLabelText('Final editing workflow')).getByText(/document excerpt are unavailable/)).toBeTruthy();
 expect(Boolean(screen.queryByText(/Private final edit/))).toBe(status==='accepted');
 expect(Boolean(screen.queryByText(/Author synthetic abstract/))).toBe(status==='accepted');
});

it('shows recorded invitation times and explicit missing response without inventing a timezone', async()=>{
 const item={manuscript_id:7,title:'Synthetic title',status:'initial_editor_invited',invitation:{invitation_id:3,status:'pending',editor:'Synthetic Editor',invited_at:'2026-02-01T12:30:00',responded_at:null},submissions:[]};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[item]})));
 render(<InitialEditingPanel role="editor" token="synthetic" onChanged={async()=>{}}/>);
 fireEvent.click(await screen.findByText('Initial editor invitation information'));
 expect(screen.getByText(/2026-02-01T12:30:00 \(timezone not recorded\)/)).toBeTruthy();
 expect(screen.getByText('Responded:').parentElement.textContent).toContain('Unavailable');
 expect(screen.getByText('Invited editor:').parentElement.textContent).toContain('Synthetic Editor');
});
