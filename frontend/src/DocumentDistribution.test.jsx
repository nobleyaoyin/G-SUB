import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {EICDistribution,EditorReceivedDocuments,ReviewerDocumentUpload,ReviewerDocumentHistory} from './DocumentDistribution';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
it('shows only the selected reviewer assignment document history',async()=>{
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.includes('/10/')?[{artifact_id:'a',assignment_id:10,review_round:2,version:1,format:'txt',created_at:'2026-01-01'}]:[]})));
 const {rerender}=render(<ReviewerDocumentHistory token="synthetic" assignmentId={10}/>);
 expect(await screen.findByText(/version 1 · Round 2 · assignment #10/)).toBeTruthy();
 rerender(<ReviewerDocumentHistory token="synthetic" assignmentId={11}/>);
 expect(screen.queryByText(/version 1 · Round 2 · assignment #10/)).toBeNull();
 expect(await screen.findByText('No reviewed documents recorded for this assignment.')).toBeTruthy();
});
it('separates each round and assignment’s comments from actual reviewed documents',async()=>{
 const artifacts=[{artifact_id:'a',assignment_id:11,review_round:2,version:1,format:'pdf'}];
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/reviewed-documents')?artifacts:url.endsWith('/candidates')?{document:null,recipients:[]}:[]})));
 const overview={manuscript:{manuscript_id:7},assignments:[
  {assignment_id:10,review_round:1,status:'completed',review:{comments:'First review',recommendation:'accept',submitted_at:'2026-01-01'}},
  {assignment_id:11,review_round:2,status:'completed',review:{comments:'Second review',recommendation:'revise'}},
  {assignment_id:12,review_round:3,status:'assigned',review:null},
 ]};
 render(<EICDistribution token="synthetic" manuscriptId={7} overview={overview}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 expect(await screen.findByText('Review comments submitted — no reviewed document attached.')).toBeTruthy();
 expect(screen.getByText('Reviewed document: version 1 (PDF)')).toBeTruthy();
 expect(screen.getByText('Review round 3 · Assignment #12')).toBeTruthy();
 expect(screen.getByText('First review')).toBeTruthy();
 expect(screen.getByText('Second review')).toBeTruthy();
});
it('shows verified reviewed-document history when distribution candidates are unavailable',async()=>{
 vi.stubGlobal('fetch',vi.fn(async url=>url.endsWith('/candidates')?{ok:false,status:409,json:async()=>({detail:'Document unavailable'})}:{ok:true,json:async()=>[]}));
 const overview={manuscript:{manuscript_id:7},assignments:[{assignment_id:10,review_round:1,status:'completed',review:{comments:'Review',recommendation:'accept'}}]};
 render(<EICDistribution token="synthetic" manuscriptId={7} overview={overview}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 expect(await screen.findByText('Review comments submitted — no reviewed document attached.')).toBeTruthy();
 expect((await screen.findByRole('alert')).textContent).toContain('Document unavailable');
});
it('does not claim an attachment is absent when its round evidence conflicts',async()=>{
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/reviewed-documents')?[{artifact_id:'a',assignment_id:10,review_round:2,version:1,format:'pdf'}]:url.endsWith('/candidates')?{document:null,recipients:[]}:[]})));
 const overview={manuscript:{manuscript_id:7},assignments:[{assignment_id:10,review_round:1,status:'completed',review:{comments:'Review',recommendation:'accept'}}]};
 render(<EICDistribution token="synthetic" manuscriptId={7} overview={overview}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 await screen.findByText(/Round 2 · assignment #10/);
 expect(screen.getByText('Reviewed document status unavailable.')).toBeTruthy();
 expect(screen.queryByText('Review comments submitted — no reviewed document attached.')).toBeNull();
});
it('shows pre-review and recorded review round without inventing historical rounds',async()=>{
 const initial={grant_id:'i',manuscript_id:7,title:'Initial source',version:1,format:'txt',mode:'manual',round_kind:'pre_review'};
 const final={grant_id:'f',manuscript_id:8,title:'Final source',version:2,format:'txt',mode:'automatic',round_kind:'review_round',review_round:3};
 const old={grant_id:'o',manuscript_id:9,title:'Historical source',version:1,format:'txt',mode:'manual',round_kind:'historical_unknown'};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[initial,final,old]})));
 render(<EditorReceivedDocuments token="synthetic"/>);
 expect(await screen.findByText(/Initial source.*Pre-review/)).toBeTruthy();
 expect(screen.getByText(/Final source.*Review round 3/)).toBeTruthy();
 expect(screen.getByText(/Historical source.*Review round unavailable/)).toBeTruthy();
});
it('shows a safe error when distribution round evidence is unavailable',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status:503,json:async()=>({detail:'Distribution round evidence unavailable'})})));
 render(<EditorReceivedDocuments token="synthetic"/>);
 expect((await screen.findByRole('alert')).textContent).toContain('Distribution round evidence unavailable');
});
it('labels automatic provenance and an independently revoked policy in grant history',async()=>{
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/candidates')?{document:{sha256:'a'.repeat(64),format:'txt',byte_size:10},recipients:[]}:url.endsWith('/history')?[{grant_id:'auto',version:1,mode:'automatic',policy_status:'revoked',recipient_id:2,invitation_kind:'initial',invitation_id:3,actor_id:1,status:'access_granted',notification:'created',email:'not_requested'}]:[]})));
 render(<EICDistribution token="synthetic" manuscriptId={7}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 expect(await screen.findByText(/Automatic · Editor #2/)).toBeTruthy();
 expect(screen.getByText(/policy revoked; controlled access unavailable/)).toBeTruthy();
});
it('confirms an accepted editor and submits the selected digest',async()=>{
 let granted=false;
 const fetcher=vi.fn(async(url,options={})=>({ok:true,json:async()=>url.endsWith('/candidates')?{document:{sha256:'a'.repeat(64),format:'txt',byte_size:10},recipients:[{name:'Synthetic Editor',invitation_id:5,invitation_kind:'initial'}]}:url.endsWith('/reviewed-documents')?[]:options.method==='POST'?(granted=true,{grant_id:'abc',result:'access_granted'}):granted?[{grant_id:'abc',version:1,recipient_id:2,status:'access_granted',notification:'created',email:'not_requested'}]:[]}));
 vi.stubGlobal('fetch',fetcher);vi.stubGlobal('confirm',()=>true);
 render(<EICDistribution token="synthetic" manuscriptId={7}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 fireEvent.change(await screen.findByLabelText('Accepted editor'),{target:{value:'initial:5'}});
 fireEvent.change(screen.getByLabelText('Document version'),{target:{value:'a'.repeat(64)}});
 fireEvent.click(screen.getByRole('button',{name:'Confirm manual distribution'}));
 expect((await screen.findByRole('status')).textContent).toContain('Access granted');
 const sent=fetcher.mock.calls.find(([,options])=>options?.method==='POST');
 expect(JSON.parse(sent[1].body)).toMatchObject({invitation_id:5,source_sha256:'a'.repeat(64)});
});
it('shows upload after backend availability and posts a file',async()=>{
 const fetcher=vi.fn(async(url,options={})=>({ok:true,json:async()=>options.method==='POST'?{artifact_id:'synthetic',version:1,review_round:3}:{available:true}}));
 vi.stubGlobal('fetch',fetcher);
 render(<ReviewerDocumentUpload token="synthetic" assignmentId={9}/>);
 const input=await screen.findByLabelText('Reviewed file');
 fireEvent.change(input,{target:{files:[new File(['review'],'review.txt',{type:'text/plain'})]}});
 fireEvent.click(screen.getByRole('button',{name:'Upload reviewed document'}));
 await waitFor(()=>expect(screen.getByRole('status').textContent).toContain('round 3, version 1'));
 expect(fetcher.mock.calls.find(([,options])=>options?.method==='POST')[1].body.get('file').name).toBe('review.txt');
});
it('does not expose upload control when availability is denied',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status:409,json:async()=>({detail:'Unavailable'})})));
 render(<ReviewerDocumentUpload token="synthetic" assignmentId={9}/>);
 await waitFor(()=>expect(screen.queryByLabelText('Reviewed file')).toBeNull());
});

it('keeps the chosen invitation when recipients reorder after refresh',async()=>{
 let sent=0;
 const recipients=[{name:'First editor',invitation_id:5,invitation_kind:'initial'},{name:'Second editor',invitation_id:9,invitation_kind:'final'}];
 const fetcher=vi.fn(async(url,options={})=>({ok:true,json:async()=>options.method==='POST'?(sent++,{grant_id:'abc',result:'access_granted'}):url.endsWith('/candidates')?{document:{sha256:'a'.repeat(64),format:'txt',byte_size:10},recipients:sent?[...recipients].reverse():recipients}:[]}));
 vi.stubGlobal('fetch',fetcher);vi.stubGlobal('confirm',()=>true);
 render(<EICDistribution token="synthetic" manuscriptId={7}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 fireEvent.change(await screen.findByLabelText('Accepted editor'),{target:{value:'initial:5'}});
 fireEvent.change(screen.getByLabelText('Document version'),{target:{value:'a'.repeat(64)}});
 fireEvent.click(screen.getByRole('button',{name:'Confirm manual distribution'}));
 await waitFor(()=>expect(fetcher.mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(1));
 await waitFor(()=>expect(screen.getByLabelText('Accepted editor').value).toBe('initial:5'));
 fireEvent.click(screen.getByRole('button',{name:'Confirm manual distribution'}));
 await waitFor(()=>expect(fetcher.mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(2));
 expect(fetcher.mock.calls.filter(([,o])=>o?.method==='POST').map(([,o])=>JSON.parse(o.body).invitation_id)).toEqual([5,5]);
});

it('requires a chosen version and distinguishes an existing grant from a new delivery',async()=>{
 const fetcher=vi.fn(async(url,options={})=>({ok:true,json:async()=>options.method==='POST'?{grant_id:'existing',result:'access_granted',already_exists:true}:url.endsWith('/candidates')?{document:{sha256:'c'.repeat(64),format:'txt',byte_size:10},recipients:[{name:'Editor',invitation_id:5,invitation_kind:'initial'}]}:[]}));
 vi.stubGlobal('fetch',fetcher);vi.stubGlobal('confirm',()=>true);
 render(<EICDistribution token="synthetic" manuscriptId={7}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 fireEvent.change(await screen.findByLabelText('Accepted editor'),{target:{value:'initial:5'}});
 expect(screen.getByRole('button',{name:'Confirm manual distribution'}).disabled).toBe(true);
 fireEvent.change(screen.getByLabelText('Document version'),{target:{value:'c'.repeat(64)}});
 fireEvent.click(screen.getByRole('button',{name:'Confirm manual distribution'}));
 expect((await screen.findByRole('status')).textContent).toContain('no new delivery recorded');
});

it('can refresh unavailable candidate data without issuing a grant',async()=>{
 let unavailable=true;
 vi.stubGlobal('fetch',vi.fn(async url=>url.endsWith('/candidates')&&unavailable
  ? {ok:false,status:503,json:async()=>({detail:'Distribution unavailable'})}
  : {ok:true,json:async()=>url.endsWith('/candidates')?{document:{sha256:'d'.repeat(64),format:'txt',byte_size:1},recipients:[]}:[]}));
 render(<EICDistribution token="synthetic" manuscriptId={7}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 expect((await screen.findByRole('alert')).textContent).toContain('Distribution unavailable');
 unavailable=false;fireEvent.click(screen.getByRole('button',{name:'Retry distribution data'}));
 expect(await screen.findByLabelText('Document version')).toBeTruthy();
 expect(fetch.mock.calls.every(([,options])=>!options?.method||options.method==='GET')).toBe(true);
});

it('does not offer a retry for an unavailable distribution schema',async()=>{
 vi.stubGlobal('fetch',vi.fn(async url=>url.endsWith('/candidates')
  ? {ok:false,status:503,json:async()=>({detail:'Distribution schema unavailable'})}
  : {ok:true,json:async()=>[]}));
 render(<EICDistribution token="synthetic" manuscriptId={7}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 expect((await screen.findByRole('alert')).textContent).toContain('This information is currently unavailable.');
 expect(screen.queryByRole('button',{name:'Retry distribution data'})).toBeNull();
});

it('does not display a delayed previous manuscript candidate or history',async()=>{
 let release;
 const fetcher=vi.fn(url=>{
  if(url.includes('/manuscripts/1/')) return new Promise(resolve=>{(release ||= []).push(()=>resolve({ok:true,json:async()=>url.endsWith('/candidates')?{document:{sha256:'a'.repeat(64),format:'txt',byte_size:1},recipients:[{name:'Old recipient',invitation_kind:'initial',invitation_id:5}]}:[]}));});
  return Promise.resolve({ok:true,json:async()=>url.endsWith('/candidates')?{document:{sha256:'b'.repeat(64),format:'txt',byte_size:2},recipients:[{name:'Current recipient',invitation_kind:'initial',invitation_id:6}]}:[]});
 });
 vi.stubGlobal('fetch',fetcher);
 const {rerender}=render(<EICDistribution token="synthetic" manuscriptId={1}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 await waitFor(()=>expect(release).toHaveLength(6));
 rerender(<EICDistribution token="synthetic" manuscriptId={2}/>);
 expect(await screen.findByText(/Current recipient/)).toBeTruthy();
 release.forEach(done=>done());
 await waitFor(()=>expect(screen.queryByText(/Old recipient/)).toBeNull());
 expect(screen.getByText(/Current recipient/)).toBeTruthy();
});
it('does not show a delayed invitation list from the previous manuscript',async()=>{
 let release;
 vi.stubGlobal('fetch',vi.fn(url=>{
  if(url.includes('/manuscripts/1/editor-invitations'))return new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>[{invitation_kind:'initial',invitation_id:1,recipient_id:91,status:'accepted'}]})});
  return Promise.resolve({ok:true,json:async()=>url.endsWith('/editor-invitations')?[{invitation_kind:'final',invitation_id:2,recipient_id:92,status:'accepted'}]:url.endsWith('/candidates')?{document:null,recipients:[]}:[]});
 }));
 const {rerender}=render(<EICDistribution token="synthetic" manuscriptId={1}/>);
 await waitFor(()=>expect(release).toBeTypeOf('function'));
 rerender(<EICDistribution token="synthetic" manuscriptId={2}/>);
 expect(await screen.findByText(/Final Editor #92/)).toBeTruthy();
 release();await waitFor(()=>expect(screen.queryByText(/Initial Editor #91/)).toBeNull());
 expect(screen.getByText(/Final Editor #92/)).toBeTruthy();
});

it('shows only matching source-backed stage records and does not infer delivery',async()=>{
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/candidates')?{document:null,recipients:[]}:[]})));
 const overview={manuscript:{manuscript_id:7,status:'final_editing'},submissions:[{submission_id:3,editor:'Assigned editor',status:'eic_approved',created_at:'2026-01-01T00:00:00Z'}],final_workflow_submissions:[{submission_id:4,editor_id:2,status:'pending_eic'}],assignments:[{recorded_round_binding:{round_file_id:6,review_round:2,source_kind:'author_revision'}},{recorded_round_binding:{round_file_id:6,review_round:2,source_kind:'author_revision'}}]};
 const {rerender}=render(<EICDistribution token="synthetic" manuscriptId={7} overview={overview}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 expect(await screen.findByText(/Initial editing · submission #3/)).toBeTruthy();
 const binding=screen.getAllByText(/Reviewer input · Round 2/);
 expect(binding).toHaveLength(1);
 expect(binding[0].textContent).toContain('delivery not confirmed');
 expect(binding[0].textContent).not.toMatch(/delivery confirmed|digest verified/i);
 expect(screen.getByText(/Final editing · submission #4/)).toBeTruthy();
 rerender(<EICDistribution token="synthetic" manuscriptId={8} overview={overview}/>);
 expect(screen.queryByText(/Initial editing · submission #3/)).toBeNull();
 expect(screen.getByText('Stage document records unavailable.')).toBeTruthy();
});

it('lists and filters stored manuscript files without claiming delivery',async()=>{
 const fetcher=vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/versions')?[{filename:'original.txt',size_bytes:8,is_current:false},{filename:'revision.txt',size_bytes:9,is_current:true}]:url.endsWith('/candidates')?{document:null,recipients:[]}:[]}));
 vi.stubGlobal('fetch',fetcher);
 render(<EICDistribution token="synthetic" manuscriptId={7}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 expect(await screen.findByText(/original.txt · 8 bytes · Historical file/)).toBeTruthy();
 expect(screen.getByText(/revision.txt · 9 bytes · Current file/)).toBeTruthy();
 expect(screen.getByText(/Stored files do not establish submission/)).toBeTruthy();
 fireEvent.change(screen.getByLabelText('Search manuscript filenames'),{target:{value:'REVISION'}});
 expect(screen.queryByText(/original.txt · 8 bytes/)).toBeNull();
 expect(screen.getByText(/revision.txt · 9 bytes/)).toBeTruthy();
});

it('ignores obsolete manuscript version responses',async()=>{
 let release;
 vi.stubGlobal('fetch',vi.fn(url=>url.endsWith('/1/versions')?new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>[{filename:'old.txt',size_bytes:1}]})}):Promise.resolve({ok:true,json:async()=>url.endsWith('/2/versions')?[{filename:'new.txt',size_bytes:2}]:url.endsWith('/candidates')?{document:null,recipients:[]}:[]})));
 const {rerender}=render(<EICDistribution token="synthetic" manuscriptId={1}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 await waitFor(()=>expect(release).toBeTypeOf('function'));
 rerender(<EICDistribution token="synthetic" manuscriptId={2}/>);
 expect(await screen.findByText(/new.txt · 2 bytes/)).toBeTruthy();
 release();
 await waitFor(()=>expect(screen.queryByText(/old.txt · 1 bytes/)).toBeNull());
 expect(screen.getByText(/new.txt · 2 bytes/)).toBeTruthy();
});

it('loads and revokes a specific editor invitation with a reason',async()=>{
 let revoked=false;
 const fetcher=vi.fn(async(url,options={})=>{if(options.method==='POST')revoked=true;return {ok:true,json:async()=>url.endsWith('/editor-invitations')?[{invitation_kind:'final',invitation_id:4,recipient_id:2,status:revoked?'revoked':'accepted',revoked_at:revoked?'2026-01-01T00:00:00Z':null,revoked_by:1,reason:'Synthetic'}]:options.method==='POST'?{status:'revoked'}:url.endsWith('/candidates')?{document:null,recipients:[]}:[]}});
 vi.stubGlobal('fetch',fetcher);vi.stubGlobal('prompt',()=> 'Synthetic');
 render(<EICDistribution token="synthetic" manuscriptId={7}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 expect(screen.queryByRole('button',{name:'Load editor invitations'})).toBeNull();
 expect(await screen.findByText(/Final Editor #2 · invitation #4 · Accepted/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Revoke invitation'}));
 expect(await screen.findByText(/Final Editor #2 · invitation #4 · Revoked/)).toBeTruthy();
 expect(fetcher.mock.calls.find(([url])=>url.endsWith('/editor-invitations/final/4/revoke'))[1].body).toContain('Synthetic');
 expect(screen.queryByRole('button',{name:'Revoke invitation'})).toBeNull();
});
