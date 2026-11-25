import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import EICDocumentTimeline from './EICDocumentTimeline';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
it('groups recorded evidence and filters by stage, round, type and direction',async()=>{
 const events=[{id:'one',stage:'Peer Review',artifact_type:'reviewed document',direction:'inbound',review_round:2,version:1,source:'Assignment #2',destination:'G-SUB',status:'uploaded',integrity:'verified on download',download:{kind:'reviewed_document',id:'a',format:'txt'}},{id:'two',stage:'Initial Editing',artifact_type:'source grant',direction:'outbound',review_round:null,source:'G-SUB',destination:'Editor',status:'grant recorded; delivery unknown',integrity:'unknown'}];
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,events,unavailable_sources:[]})})));
 const download=vi.fn();render(<EICDocumentTimeline token="synthetic" manuscriptId={7} onDownload={download}/>);
 expect(await screen.findByRole('heading',{name:'Review round 2'})).toBeTruthy();
 expect(screen.getByRole('option',{name:'Peer review'}).value).toBe('Peer Review');
 expect(screen.getByText(/Peer review · reviewed document/)).toBeTruthy();
 expect(screen.getByText(/Grant recorded; delivery unknown/)).toBeTruthy();
 fireEvent.change(screen.getByLabelText('Filter direction'),{target:{value:'inbound'}});
 expect(screen.queryByText(/Grant recorded; delivery unknown/)).toBeNull();
 fireEvent.change(screen.getByLabelText('Filter stage'),{target:{value:'Peer Review'}});
 fireEvent.change(screen.getByLabelText('Filter round'),{target:{value:'2'}});
 fireEvent.change(screen.getByLabelText('Filter artifact type'),{target:{value:'reviewed document'}});
 fireEvent.click(screen.getByRole('button',{name:'Download reviewed document'}));expect(download).toHaveBeenCalledWith({kind:'reviewed_document',id:'a',format:'txt'});
});
it('does not show a previous manuscript after switching',async()=>{
 let release;vi.stubGlobal('fetch',vi.fn(url=>url.includes('/1/')?new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({manuscript_id:1,events:[{id:'old',stage:'Old',artifact_type:'old',direction:'inbound'}],unavailable_sources:[]})})}):Promise.resolve({ok:true,json:async()=>({manuscript_id:2,events:[],unavailable_sources:[]})})));
 const {rerender}=render(<EICDocumentTimeline token="synthetic" manuscriptId={1}/>);rerender(<EICDocumentTimeline token="synthetic" manuscriptId={2}/>);
 expect(await screen.findByText('No matching document records.')).toBeTruthy();release();expect(screen.queryByText(/Old · old/)).toBeNull();
});
it('formats recorded dates and omits unknown metadata without hiding the event',async()=>{
 const event={id:'undirected',stage:'Final Editing',artifact_type:'editing submission',direction:'unknown',timestamp:'2026-11-21T15:31:32.123456',source:'AUTHOR',destination:'unknown',status:'uploaded',integrity:'unknown'};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,events:[event],unavailable_sources:[]})})));
 render(<EICDocumentTimeline token="synthetic" manuscriptId={7}/>);
 expect(await screen.findByText(/Final editing · editing submission/)).toBeTruthy();
 expect(screen.getByText(/From: Author/)).toBeTruthy();
 expect(screen.getByText(/2026.*3:31.*timezone not recorded/)).toBeTruthy();
 expect(screen.queryByText(/Direction unknown/)).toBeNull();
 expect(screen.queryByText(/version unavailable|integrity: unknown/i)).toBeNull();
});
it('offers a formatting download for the exact recorded artifact',async()=>{
 const event={id:'formatting:3',stage:'Formatting',artifact_type:'formatting submission',direction:'inbound',status:'uploaded; review approved',source:'Formatter',destination:'G-SUB',integrity:'verified on download',download:{kind:'formatting',id:3}};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,events:[event],unavailable_sources:[]})})));
 const download=vi.fn();render(<EICDocumentTimeline token="synthetic" manuscriptId={7} onDownload={download}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Download formatting document'}));
 expect(download).toHaveBeenCalledWith({kind:'formatting',id:3});
});
it('distinguishes grant notification from download and email evidence',async()=>{
 const event={id:'grant:1',stage:'Initial Editing',artifact_type:'editor source grant',direction:'outbound',status:'manual grant recorded; delivery unknown',source:'G-SUB',destination:'Editor',integrity:'digest recorded; not verified',notification_evidence:'created',email_evidence:'not_requested',download_evidence:'unknown'};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,events:[event],unavailable_sources:[]})})));
 render(<EICDocumentTimeline token="synthetic" manuscriptId={7}/>);
 expect(await screen.findByText(/in-app notification state: created · email: not requested/)).toBeTruthy();
 expect(screen.queryByText(/download receipt: unavailable/)).toBeNull();
});
it('offers the exact recorded submitted source to its EIC download handler',async()=>{
 const event={id:'submission-snapshot:x',stage:'Submission',artifact_type:'author submission source',direction:'inbound',status:'submitted',source:'Author',destination:'G-SUB',integrity:'verified on download',download:{kind:'author_submission',id:'a'.repeat(32)}};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,events:[event],unavailable_sources:[]})})));
 const download=vi.fn();render(<EICDocumentTimeline token="synthetic" manuscriptId={7} onDownload={download}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Download submitted document'}));expect(download).toHaveBeenCalledWith(event.download);
});
it('offers the recorded final edit without claiming digest evidence',async()=>{
 const event={id:'final:9',stage:'Final Editing',artifact_type:'editing submission',direction:'inbound',status:'uploaded',source:'Final Editor',destination:'G-SUB',integrity:'unavailable',download:{kind:'final_editing',id:9}};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,events:[event],unavailable_sources:[]})})));
 const download=vi.fn();render(<EICDocumentTimeline token="synthetic" manuscriptId={7} onDownload={download}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Download final edit'}));expect(download).toHaveBeenCalledWith(event.download);expect(screen.queryByText(/integrity: unavailable/i)).toBeNull();
});
