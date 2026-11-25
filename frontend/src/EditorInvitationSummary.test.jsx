import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import InitialEditingPanel from './InitialEditingPanel';
import FinalEditingPanel from './FinalEditingPanel';
import {recordedTimestamp} from './recordedTimestamp';
vi.mock('./OnlineDocumentEditor',()=>({default:()=>null}));
vi.mock('./OnlineDocxEditor',()=>({default:()=>null}));
afterEach(()=>{cleanup();vi.unstubAllGlobals()});

it('does not present missing, malformed or impossible timestamps as recorded dates',()=>{
 expect(recordedTimestamp(null)).toBe('Unavailable');
 expect(recordedTimestamp('not-a-date')).toBe('Unavailable');
 expect(recordedTimestamp('2026-02-30T12:30:00')).toBe('Unavailable');
 expect(recordedTimestamp('2026-02-01T12:30:00')).toContain('timezone not recorded');
 expect(recordedTimestamp('2026-02-01T12:30:00+00:00')).toBe('2026-02-01T12:30:00+00:00');
});

it.each(['pending','declined','accepted'])('initial invitation %s reveals only appropriate history',async status=>{
 const item={manuscript_id:7,title:'Synthetic title',invitation_abstract:'Author synthetic abstract',status:'initial_editor_invited',invitation:{invitation_id:3,status,editor:'Editor'},submissions:[{submission_id:5,status:'pending_author',comments:'Private edit'}]};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[item]})));
 render(<InitialEditingPanel role="editor" token="synthetic" onChanged={async()=>{}}/>);
 fireEvent.click(await screen.findByText('Initial editor invitation information'));
 expect(screen.getByText(/Subject, keywords, table count/)).toBeTruthy();
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

it.each(['initial','final'])('%s invitation displays a sourced advisory count without revealing a pending abstract',async kind=>{
 const metadata={word_count:4,word_count_source:'Advisory local TXT analysis of latest author-submission snapshot, round 1'};
 const item=kind==='initial' ? {manuscript_id:7,title:'Synthetic',status:'initial_editor_invited',invitation:{invitation_id:3,status:'pending',editor:'Editor'},invitation_metadata:metadata,invitation_abstract:'private',submissions:[]} : {manuscript_id:7,title:'Synthetic',status:'pending',manuscript_status:'final_editing',invitation_id:3,invitation_metadata:metadata,invitation_abstract:'private',submissions:[]};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[item]})));
 const Panel=kind==='initial'?InitialEditingPanel:FinalEditingPanel;
 render(<Panel role="editor" token="synthetic" onChanged={async()=>{}}/>);
 fireEvent.click(await screen.findByText(`${kind==='initial'?'Initial':'Final'} editor invitation information`));
 expect(screen.getByText(/Advisory local TXT analysis/).textContent).toContain('estimate');
 expect(screen.getByText('Word count:').parentElement.textContent).toContain('4');
 expect(screen.queryByText('private')).toBeNull();
 expect(screen.getByText('Figure count:').parentElement.textContent).toContain('Unavailable');
 expect(screen.getByRole('button',{name:kind==='initial'?'Accept invitation':'Accept final editor invitation'})).toBeTruthy();
});

it.each(['initial','final'])('%s invitation treats invalid metadata as unavailable',async kind=>{
 const metadata={word_count:42,word_count_source:'  ',subject:'Do not expose'};
 const item=kind==='initial' ? {manuscript_id:7,title:'Synthetic',status:'initial_editor_invited',invitation:{invitation_id:3,status:'pending',editor:'Editor',invited_at:'not-a-date'},invitation_metadata:metadata,submissions:[]} : {manuscript_id:7,title:'Synthetic',status:'pending',manuscript_status:'final_editing',invitation_id:3,invitation_metadata:metadata,invited_at:'not-a-date',submissions:[]};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[item]})));
 const Panel=kind==='initial'?InitialEditingPanel:FinalEditingPanel;
 render(<Panel role="editor" token="synthetic" onChanged={async()=>{}}/>);
 fireEvent.click(await screen.findByText(`${kind==='initial'?'Initial':'Final'} editor invitation information`));
 expect(screen.getByText('Word count:').parentElement.textContent).toContain('Unavailable');
 expect(screen.queryByText('Do not expose')).toBeNull();
 expect(screen.queryByText(/not-a-date/)).toBeNull();
});
