import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {EICDistribution,ReviewerDocumentUpload} from './DocumentDistribution';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
it('confirms an accepted editor and submits the selected digest',async()=>{
 let granted=false;
 const fetcher=vi.fn(async(url,options={})=>({ok:true,json:async()=>url.endsWith('/candidates')?{document:{sha256:'a'.repeat(64),format:'txt',byte_size:10},recipients:[{name:'Synthetic Editor',invitation_id:5,invitation_kind:'initial'}]}:url.endsWith('/reviewed-documents')?[]:options.method==='POST'?(granted=true,{grant_id:'abc',result:'access_granted'}):granted?[{grant_id:'abc',version:1,recipient_id:2,status:'access_granted',notification:'created',email:'not_requested'}]:[]}));
 vi.stubGlobal('fetch',fetcher);vi.stubGlobal('confirm',()=>true);
 render(<EICDistribution token="synthetic" manuscriptId={7}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 fireEvent.change(await screen.findByLabelText('Accepted editor'),{target:{value:'initial:5'}});
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
 fireEvent.click(screen.getByRole('button',{name:'Confirm manual distribution'}));
 await waitFor(()=>expect(fetcher.mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(1));
 await waitFor(()=>expect(screen.getByLabelText('Accepted editor').value).toBe('initial:5'));
 fireEvent.click(screen.getByRole('button',{name:'Confirm manual distribution'}));
 await waitFor(()=>expect(fetcher.mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(2));
 expect(fetcher.mock.calls.filter(([,o])=>o?.method==='POST').map(([,o])=>JSON.parse(o.body).invitation_id)).toEqual([5,5]);
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
 await waitFor(()=>expect(release).toHaveLength(4));
 rerender(<EICDistribution token="synthetic" manuscriptId={2}/>);
 expect(await screen.findByText(/Current recipient/)).toBeTruthy();
 release.forEach(done=>done());
 await waitFor(()=>expect(screen.queryByText(/Old recipient/)).toBeNull());
 expect(screen.getByText(/Current recipient/)).toBeTruthy();
});

it('shows only matching source-backed stage records and does not infer delivery',async()=>{
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/candidates')?{document:null,recipients:[]}:[]})));
 const overview={manuscript:{manuscript_id:7,status:'final_editing'},submissions:[{submission_id:3,editor:'Assigned editor',status:'eic_approved',created_at:'2026-01-01T00:00:00Z'}],final_workflow_submissions:[{submission_id:4,editor_id:2,status:'pending_eic'}],assignments:[{recorded_round_binding:{round_file_id:6,review_round:2,source_kind:'author_revision'}},{recorded_round_binding:{round_file_id:6,review_round:2,source_kind:'author_revision'}}]};
 const {rerender}=render(<EICDistribution token="synthetic" manuscriptId={7} overview={overview}/>);
 fireEvent.click(screen.getByText('Document distribution and generation history'));
 expect(await screen.findByText(/Initial editing · submission #3/)).toBeTruthy();
 expect(screen.getAllByText(/Reviewer input · round 2/)).toHaveLength(1);
 expect(screen.getByText(/delivery and digest unknown/)).toBeTruthy();
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
