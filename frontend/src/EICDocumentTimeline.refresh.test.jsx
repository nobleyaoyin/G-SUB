import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import EICDocumentTimeline from './EICDocumentTimeline';
import {EICDistribution} from './DocumentDistribution';

afterEach(()=>{cleanup();vi.unstubAllGlobals()});

it('refreshes after a workflow revision and ignores an older response',async()=>{
 let release;
 const old={id:'old',stage:'Old stage',artifact_type:'old record',direction:'inbound'};
 const fresh={id:'new',stage:'Peer Review',artifact_type:'assignment source binding',direction:'outbound',status:'bound; delivery unknown'};
 const fetcher=vi.fn().mockImplementationOnce(()=>new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({manuscript_id:7,events:[old],unavailable_sources:[]})})}))
  .mockResolvedValueOnce({ok:true,json:async()=>({manuscript_id:7,events:[fresh],unavailable_sources:[]})});
 vi.stubGlobal('fetch',fetcher);
 const {rerender}=render(<EICDocumentTimeline token="synthetic" manuscriptId={7} revision={0}/>);
 rerender(<EICDocumentTimeline token="synthetic" manuscriptId={7} revision={1}/>);
 expect(await screen.findByText(/Bound; delivery unknown/)).toBeTruthy();
 release();await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(2));
 expect(screen.queryByText(/Old stage/)).toBeNull();
});

it('retains the selected filter across a refresh of the same manuscript',async()=>{
 const events=[{id:'one',stage:'Peer Review',artifact_type:'binding',direction:'outbound',status:'bound'},
  {id:'two',stage:'Submission',artifact_type:'source',direction:'inbound',status:'submitted'}];
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,events,unavailable_sources:[]})})));
 const {rerender}=render(<EICDocumentTimeline token="synthetic" manuscriptId={7} revision={0}/>);
 fireEvent.change(await screen.findByLabelText('Filter stage'),{target:{value:'Peer Review'}});
 expect(screen.queryByText(/Submitted/)).toBeNull();
 rerender(<EICDocumentTimeline token="synthetic" manuscriptId={7} revision={1}/>);
 await screen.findByRole('listitem');
 expect(screen.getByLabelText('Filter stage').value).toBe('Peer Review');
 expect(screen.queryByText(/Submitted/)).toBeNull();
});

it('refreshes timeline evidence after an actual successful grant response',async()=>{
 let granted=false;
 const event={id:'grant:abc',stage:'Initial Editing',artifact_type:'editor source grant',direction:'outbound',status:'grant recorded; delivery unknown'};
 const fetcher=vi.fn(async(url,options={})=>({ok:true,json:async()=>{
  if(url.endsWith('/document-timeline'))return {manuscript_id:7,events:granted?[event]:[],unavailable_sources:[]};
  if(url.endsWith('/candidates'))return {document:{sha256:'a'.repeat(64),format:'txt',byte_size:10},recipients:[{name:'Synthetic Editor',invitation_id:5,invitation_kind:'initial'}]};
  if(options.method==='POST'){granted=true;return {grant_id:'abc',result:'access_granted'};}
  return [];
 }}));
 vi.stubGlobal('fetch',fetcher);vi.stubGlobal('confirm',()=>true);
 render(<EICDistribution token="synthetic" manuscriptId={7}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 expect(await screen.findByText('No matching document records.')).toBeTruthy();
 fireEvent.change(await screen.findByLabelText('Accepted editor'),{target:{value:'initial:5'}});
 fireEvent.change(screen.getByLabelText('Document version'),{target:{value:'a'.repeat(64)}});
 fireEvent.click(screen.getByRole('button',{name:'Confirm manual distribution'}));
 expect(await screen.findByText(/Grant recorded; delivery unknown/)).toBeTruthy();
 expect(fetcher.mock.calls.filter(([url])=>url.endsWith('/document-timeline')).length).toBeGreaterThanOrEqual(2);
});
