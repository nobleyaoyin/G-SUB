import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {webcrypto} from 'node:crypto';
import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import GuidedSubmissionWizard from './GuidedSubmissionWizard';

vi.mock('../DocumentDistribution',()=>({ManuscriptVersionHistory:()=>null}));
beforeEach(()=>{const values=new Map();vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('localStorage',{getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,String(value)),removeItem:key=>values.delete(key),clear:()=>values.clear()});});
afterEach(()=>{cleanup();window.localStorage.clear();vi.unstubAllGlobals();});

function fixture(existing=null, settings={}) {
  let draft=existing, manuscript={manuscript_id:42,title:'Synthetic title',status:settings.manuscriptStatus||'draft',has_pdf:Boolean(settings.currentVersion),file_type:settings.currentVersion?'txt':null}, attachments=[], receipt=settings.existingReceipt||null;
  const response=(value,status=200)=>({ok:status>=200&&status<300,status,json:async()=>structuredClone(value)});
  const fetcher=vi.fn(async(url,options={})=>{
    const path=String(url),method=options.method||'GET';
    if(path.endsWith('/configuration'))return response({submission_types:['Review Article']});
    if(path.endsWith('/requirements'))return response({keywords_required:true,cover_letter_required:false,corresponding_author_required:['first_name','last_name','email','institution','country'],coauthor_required:['first_name','last_name','institution','country']});
    if(path.endsWith('/author/submission-drafts')&&method==='GET'){if(settings.initialNetworkFailures>0){settings.initialNetworkFailures--;throw Error('network error');}if(settings.initialFailures>0){settings.initialFailures--;return response({detail:'internal database detail'},503);}return response(draft?[draft]:[]);}
    if(path.endsWith('/author/submission-drafts')&&method==='POST'){draft={id:'abc',revision:0,current_step:1,payload:{}};return response(draft,201);}
    if(path.endsWith('/author/submission-drafts/abc')&&method==='GET')return response(draft);
    if(path.endsWith('/author/submission-drafts/abc')&&method==='PUT'){const data=JSON.parse(options.body);if(settings.waitSave)await settings.waitSave;if(settings.failSave)throw Error('Network unavailable');if(settings.validationErrors)return response({detail:{code:'submission_validation',errors:settings.validationErrors}},422);if(settings.conflict || data.revision!==draft.revision)return response({detail:'Conflict'},409);draft={...draft,revision:draft.revision+1,current_step:data.current_step,payload:data.payload};return response(draft);}
    if(path.endsWith('/author/submission-drafts/abc/link'))return response({manuscript_id:42});
    if(path.endsWith('/author/submission-drafts/abc/attachments')&&method==='GET')return response(attachments);
    if(path.endsWith('/author/submission-drafts/abc/attachments')&&method==='POST'){if(settings.attachmentFailure)return response({},settings.attachmentFailure);const file=options.body.get('file');attachments.push({id:settings.lostAttachmentResponse?options.body.get('request_id'):String(attachments.length+1),kind:options.body.get('kind'),filename:file.name,size:file.size,removed_at:null});if(settings.lostAttachmentResponse)throw Error('Response lost');return response(attachments.at(-1),201);}
    if(path.endsWith('/manuscripts/42')&&method==='GET')return response(manuscript);
    if(path.endsWith('/manuscripts/42/versions')&&method==='GET')return response(settings.currentVersion?[settings.currentVersion]:[]);
    if(path.includes('/manuscripts/42/upload-requests/')&&method==='GET')return settings.legacyRecovery?response({detail:'Unavailable'},503):receipt?response(receipt):response({detail:'Not found'},404);
    if(path.endsWith('/manuscripts/42/upload-recovery')&&method==='GET')return response({available:!settings.legacyRecovery});
    if(path.includes('/manuscripts/42/submit')&&method==='POST'){expect(options.headers['X-Expected-Submission-Revision']).toBe(String(draft.revision));expect(options.headers['X-Submission-Request-ID']).toBe(window.localStorage.getItem('gsub:pending-submission:abc:42'));manuscript={...manuscript,status:'submitted'};if(settings.lostSubmitResponse)throw Error('Response lost');return response(manuscript);}
    throw Error(`Unexpected request ${method} ${path}`);
  });
  vi.stubGlobal('fetch',fetcher);
  const upload=vi.fn(async(_id,file,requestId)=>{if(settings.legacyFailure)throw new TypeError('Network lost');manuscript={...manuscript,has_pdf:true,file_type:'txt'};const pending=JSON.parse(window.localStorage.getItem('gsub:pending-manuscript-upload:abc:42'));receipt={request_id:requestId,manuscript_id:42,original_filename:settings.normalizedReceipt?file.name.normalize('NFC'):file.name,size:file.size,sha256:pending.sha256,is_current:true};if(settings.lostMainUpload)throw new TypeError('Network lost');return {filename:'source.txt'};});
  render(<GuidedSubmissionWizard token="synthetic" onClose={vi.fn()} onOpenManuscript={vi.fn()} onUploadFile={upload} onDownloadCurrent={vi.fn()} documentDirty={settings.documentDirty} onDiscardDocumentEdits={settings.onDiscard} />);
  return {fetcher,upload,getDraft:()=>draft};
}

async function press(name){fireEvent.click(await screen.findByRole('button',{name}));}
async function step(number){await screen.findByText(new RegExp(`Step ${number} of 10`));}

describe('guided submission',()=>{
  it('keeps Start disabled on an initialization failure and recovers after retry',async()=>{
    const log=vi.spyOn(console,'error').mockImplementation(()=>{});
    try {
      fixture(null,{initialFailures:1});
      expect((await screen.findByRole('alert')).textContent).toContain('temporarily unavailable');
      expect(screen.getByRole('button',{name:'Start'}).disabled).toBe(true);
      expect(screen.queryByText('internal database detail')).toBeNull();
      await press('Try again');
      await waitFor(()=>expect(screen.getByRole('button',{name:'Start'}).disabled).toBe(false));
      await press('Start');await step(2);
      expect(log).toHaveBeenCalledWith('Submission request failed', {status:503,method:'GET'});
    } finally {log.mockRestore();}
  });
  it('distinguishes connection failures and allows initialization to be retried',async()=>{
    const log=vi.spyOn(console,'error').mockImplementation(()=>{});
    try {
      fixture(null,{initialNetworkFailures:1});
      expect((await screen.findByRole('alert')).textContent).toContain('Check your connection');
      expect(screen.getByRole('button',{name:'Start'}).disabled).toBe(true);
      await press('Try again');
      await waitFor(()=>expect(screen.getByRole('button',{name:'Start'}).disabled).toBe(false));
    } finally {log.mockRestore();}
  });
  it('persists ten steps and submits using the saved revision',async()=>{
    const state=fixture();
    await waitFor(()=>expect(screen.getByRole('button',{name:'Start'}).disabled).toBe(false));
    await press('Start');await step(2);
    fireEvent.change(screen.getByLabelText(/Submission type/),{target:{value:'Review Article'}});await press('Next');await step(3);
    fireEvent.change(screen.getByLabelText(/Document title/),{target:{value:'Synthetic title'}});await press('Next');await step(4);
    fireEvent.change(screen.getByLabelText(/Abstract/),{target:{value:'Synthetic abstract'}});await press('Next');await step(5);
    await waitFor(()=>expect(screen.getByRole('button',{name:'Upload manuscript'}).disabled).toBe(true));
    fireEvent.change(screen.getByLabelText(/Select manuscript file/),{target:{files:[new File(['data'],'source.txt',{type:'text/plain'})]}});
    await press('Upload manuscript');await screen.findByText(/Current file:/);await press('Next');await step(6);
    fireEvent.change(screen.getByLabelText('Keyword'),{target:{value:'research'}});await press('Add keyword');await press('Next');await step(7);
    const author=screen.getByRole('group',{name:'Corresponding author'});
    for(const [label,value] of [['First name','Ada'],['Last name','Author'],['Email','ada@example.com'],['Institution','University'],['Country','Country']])fireEvent.change(within(author).getByLabelText(new RegExp(`^${label}`)),{target:{value}});
    await press('Next');await step(8);
    fireEvent.change(screen.getByLabelText(/Corresponding author position/),{target:{value:'0'}});
    await press('Add co-author');const coauthor=screen.getByRole('group',{name:'Co-author 1'});
    for(const [label,value] of [['First name','Bob'],['Last name','Researcher'],['Institution','University'],['Country','Country']])fireEvent.change(within(coauthor).getByLabelText(new RegExp(`^${label}`)),{target:{value}});
    await press('Next');await step(9);
    fireEvent.change(screen.getByLabelText('Cover letter text'),{target:{value:'Cover letter'}});
    fireEvent.change(screen.getByLabelText('Upload attachment'),{target:{files:[new File(['cover'],'cover.txt',{type:'text/plain'})]}});
    await screen.findByText(/cover.txt/);await press('Next');await step(10);
    fireEvent.change(screen.getByLabelText('Supplementary files included?'),{target:{value:'true'}});
    fireEvent.change(screen.getByLabelText('Upload supplementary file'),{target:{files:[new File(['supp'],'supp.txt',{type:'text/plain'})]}});
    await screen.findByText(/supp.txt/);await press('Next');await screen.findByText('Review and submit');
    await press('Submit manuscript');await screen.findByText('Submission successful');
    expect(state.getDraft().payload.corresponding_author.first_name).toBe('Ada');
    expect(state.getDraft().payload.coauthors[0].last_name).toBe('Researcher');
    expect(state.upload).toHaveBeenCalledOnce();
    expect(screen.getByText('Status: submitted')).toBeTruthy();
  });

  it('resumes saved values without creating another draft',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:3,payload:{submission_type:'Review Article',title:'Saved title'}});
    await press(/Saved title · Step 3/);
    await step(3);
    expect(screen.getByLabelText(/Document title/).value).toBe('Saved title');
    expect(state.fetcher.mock.calls.filter(([url,options])=>String(url).endsWith('/author/submission-drafts')&&options?.method==='POST')).toHaveLength(0);
  });

  it('preserves local edits on a revision conflict and asks before reloading',async()=>{
    fixture({id:'abc',revision:3,current_step:3,payload:{submission_type:'Review Article',title:'Saved title'}},{conflict:true});
    vi.stubGlobal('confirm',vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true));
    await press(/Saved title · Step 3/);await step(3);
    fireEvent.change(screen.getByLabelText(/Document title/),{target:{value:'Unsaved title'}});
    await press('Save draft');await screen.findByRole('alert');
    expect(screen.getByLabelText(/Document title/).value).toBe('Unsaved title');
    await press('Reload saved draft');expect(screen.getByLabelText(/Document title/).value).toBe('Unsaved title');
    await press('Reload saved draft');await waitFor(()=>expect(screen.getByLabelText(/Document title/).value).toBe('Saved title'));
  });

  it('protects unsaved document edits when leaving the file step',async()=>{
    const discard=vi.fn();fixture({id:'abc',revision:3,current_step:5,payload:{title:'Saved title',abstract:'Saved abstract'}},{documentDirty:true,onDiscard:discard});
    vi.stubGlobal('confirm',vi.fn().mockReturnValueOnce(true).mockReturnValueOnce(false));
    await press(/Saved title · Step 5/);await step(5);
    discard.mockClear();
    await press('Previous');expect(screen.getByText(/Step 5 of 10/)).toBeTruthy();expect(discard).not.toHaveBeenCalled();
  });

  it('debounces edits and saves the latest value with the current revision',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:3,payload:{submission_type:'Review Article',title:'Saved title'}});
    await press(/Saved title · Step 3/);await step(3);
    const title=screen.getByLabelText(/Document title/);
    fireEvent.change(title,{target:{value:'First edit'}});
    fireEvent.change(title,{target:{value:'Final edit'}});
    expect(screen.getByText('Unsaved changes')).toBeTruthy();
    expect(state.fetcher.mock.calls.filter(([url,options])=>String(url).endsWith('/abc')&&options?.method==='PUT')).toHaveLength(0);
    await waitFor(()=>expect(state.getDraft().payload.title).toBe('Final edit'),{timeout:3000});
    expect(state.getDraft().revision).toBe(4);
    expect(state.fetcher.mock.calls.filter(([url,options])=>String(url).endsWith('/abc')&&options?.method==='PUT')).toHaveLength(1);
    expect(screen.getByText('Saved')).toBeTruthy();
  });

  it('keeps failed autosave edits visible without retrying indefinitely',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:3,payload:{submission_type:'Review Article',title:'Saved title'}},{failSave:true});
    await press(/Saved title · Step 3/);await step(3);
    fireEvent.change(screen.getByLabelText(/Document title/),{target:{value:'Local edit'}});
    await screen.findByText(/Save failed/,{},{timeout:3000});
    expect(screen.getByLabelText(/Document title/).value).toBe('Local edit');
    expect(state.getDraft().payload.title).toBe('Saved title');
  });

  it('prevents overlapping actions while a delayed autosave is in flight',async()=>{
    let release;const waitSave=new Promise(resolve=>{release=resolve;});
    const state=fixture({id:'abc',revision:3,current_step:3,payload:{submission_type:'Review Article',title:'Saved title'}},{waitSave});
    await press(/Saved title · Step 3/);await step(3);
    fireEvent.change(screen.getByLabelText(/Document title/),{target:{value:'Pending edit'}});
    await waitFor(()=>expect(screen.getAllByText('Saving…').length).toBeGreaterThan(0),{timeout:3000});
    expect(screen.getByLabelText(/Document title/).closest('fieldset').disabled).toBe(true);
    expect(screen.getByRole('button',{name:'Save draft'}).disabled).toBe(true);
    expect(state.getDraft().revision).toBe(3);
    release();await waitFor(()=>expect(state.getDraft().revision).toBe(4));
    expect(state.getDraft().payload.title).toBe('Pending edit');
  });

  it('shows required title validation beside the field',async()=>{
    fixture({id:'abc',revision:3,current_step:3,payload:{submission_type:'Review Article',title:''}});
    await press(/Untitled draft · Step 3/);await step(3);await press('Next');
    expect(screen.getByLabelText(/Document title/).getAttribute('aria-invalid')).toBe('true');
    expect(screen.getAllByText('Enter a title of no more than 255 characters.').length).toBeGreaterThan(0);
  });

  it('identifies missing corresponding author fields beside their inputs',async()=>{
    fixture({id:'abc',revision:3,current_step:7,payload:{title:'Saved title',abstract:'Saved abstract',corresponding_author:{first_name:'Ada',last_name:'',email:'invalid',institutions:[{name:'',country:''}]}}});
    await press(/Saved title · Step 7/);await step(7);await press('Next');
    const author=screen.getByRole('group',{name:'Corresponding author'});
    expect(within(author).getByLabelText(/^Last name/).getAttribute('aria-invalid')).toBe('true');
    expect(within(author).getByLabelText(/^Email/).getAttribute('aria-invalid')).toBe('true');
    expect(within(author).getByText('Enter a valid email address.')).toBeTruthy();
  });

  it('associates backend numeric errors with the input and focuses it from the summary',async()=>{
    fixture({id:'abc',revision:3,current_step:10,payload:{title:'Saved title',abstract:'Saved abstract'}},{validationErrors:[{step:10,field:'manuscript_information.figures',message:'Enter a nonnegative figure count.'}]});
    await press(/Saved title · Step 10/);await step(10);await press('Save draft');
    const input=screen.getByLabelText(/Number of figures/);
    await waitFor(()=>expect(input.getAttribute('aria-invalid')).toBe('true'));
    const id=input.getAttribute('aria-describedby');
    expect(document.getElementById(id).textContent).toBe('Enter a nonnegative figure count.');
    fireEvent.click(screen.getByRole('button',{name:/Enter a nonnegative figure count/}));
    await waitFor(()=>expect(document.activeElement).toBe(input));
  });

  it('maps indexed keyword validation to its editable input',async()=>{
    fixture({id:'abc',revision:3,current_step:6,payload:{title:'Saved title',abstract:'Saved abstract',keywords:['research']}},{validationErrors:[{step:6,field:'keywords.0',message:'Check this keyword.'}]});
    await press(/Saved title · Step 6/);await step(6);await press('Save draft');
    const input=screen.getByLabelText('Keyword 1');
    await waitFor(()=>expect(input.getAttribute('aria-invalid')).toBe('true'));
    expect(document.getElementById(input.getAttribute('aria-describedby')).textContent).toBe('Check this keyword.');
    fireEvent.click(screen.getByRole('button',{name:/Check this keyword/}));
    await waitFor(()=>expect(document.activeElement).toBe(input));
  });

  it('associates attachment validation with the selected file input',async()=>{
    fixture({id:'abc',revision:3,current_step:9,payload:{title:'Saved title',abstract:'Saved abstract'}},{attachmentFailure:413});
    await press(/Saved title · Step 9/);await step(9);
    const input=screen.getByLabelText('Upload attachment');
    fireEvent.change(input,{target:{files:[new File(['cover'],'cover.txt')]}});
    await waitFor(()=>expect(input.getAttribute('aria-invalid')).toBe('true'));
    expect(document.getElementById(input.getAttribute('aria-describedby')).textContent).toBe('The selected file is too large.');
    fireEvent.click(screen.getByRole('button',{name:/The selected file is too large/}));
    await waitFor(()=>expect(document.activeElement).toBe(input));
  });

  it('focuses the controlling selection when a conditional field is hidden',async()=>{
    fixture({id:'abc',revision:3,current_step:10,payload:{title:'Saved title',abstract:'Saved abstract',funding:{has_funding:false}}},{validationErrors:[{step:10,field:'funding.name',message:'Check funding.'}]});
    await press(/Saved title · Step 10/);await step(10);await press('Save draft');
    fireEvent.click(await screen.findByRole('button',{name:/Check funding/}));
    await waitFor(()=>expect(document.activeElement).toBe(screen.getByLabelText('Funding to report?')));
  });

  it('routes the corresponding author position error to its actual step',async()=>{
    fixture({id:'abc',revision:3,current_step:8,payload:{title:'Saved title',abstract:'Saved abstract'}},{validationErrors:[{step:7,field:'corresponding_author_position',message:'Choose an author position.'}]});
    await press(/Saved title · Step 8/);await step(8);await press('Save draft');
    const input=screen.getByLabelText(/Corresponding author position/);
    await waitFor(()=>expect(input.getAttribute('aria-invalid')).toBe('true'));
    fireEvent.click(screen.getByRole('button',{name:/Choose an author position.*step 8/}));
    await waitFor(()=>expect(document.activeElement).toBe(input));
  });

  it('focuses an indexed co-author affiliation reported by the backend',async()=>{
    fixture({id:'abc',revision:3,current_step:8,payload:{title:'Saved title',abstract:'Saved abstract',coauthors:[{first_name:'Ada',institutions:[{name:'First',country:'US'},{name:'Second',country:'US'}]}]}},{validationErrors:[{step:8,field:'coauthors.0.institutions.1.name',message:'Check the second institution.'}]});
    await press(/Saved title · Step 8/);await step(8);await press('Save draft');
    const input=within(screen.getByRole('group',{name:'Institution 2'})).getByLabelText('Institution');
    await waitFor(()=>expect(input.getAttribute('aria-invalid')).toBe('true'));
    expect(document.getElementById(input.getAttribute('aria-describedby')).textContent).toBe('Check the second institution.');
    fireEvent.click(screen.getByRole('button',{name:/Check the second institution/}));
    await waitFor(()=>expect(document.activeElement).toBe(input));
  });

  it('checks server state after a submission response is lost',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:10,payload:{title:'Saved title',abstract:'Saved abstract'}},{lostSubmitResponse:true});
    await press(/Saved title · Step 10/);await step(10);await press('Next');
    await screen.findByText('Review and submit');await press('Submit manuscript');
    await screen.findByText('Submission successful');
    expect(state.fetcher.mock.calls.filter(([url,options])=>String(url).includes('/submit')&&options?.method==='POST')).toHaveLength(1);
  });

  it('restores a recorded filename when opening review from a later saved step',async()=>{
    fixture({id:'abc',revision:3,current_step:10,payload:{title:'Saved title',abstract:'Saved abstract'}},{currentVersion:{is_current:true,filename:'storage-id.txt',original_filename:'recorded.txt',size_bytes:4}});
    await press(/Saved title · Step 10/);await step(10);await press('Next');
    const review=await screen.findByText('Review and submit');
    expect(within(review.closest('.wizard-form')).getByText('recorded.txt')).toBeTruthy();
  });

  it.each(['cover_letter','supplementary'])('reconciles a lost %s upload response by request ID',async kind=>{
    const stepNumber=kind==='cover_letter'?9:10;
    const state=fixture({id:'abc',revision:3,current_step:stepNumber,payload:{title:'Saved title',abstract:'Saved abstract',manuscript_information:{has_supplementary_files:true}}},{lostAttachmentResponse:true});
    await press(new RegExp(`Saved title · Step ${stepNumber}`));await step(stepNumber);
    const label=kind==='cover_letter'?'Upload attachment':'Upload supplementary file';
    fireEvent.change(screen.getByLabelText(label),{target:{files:[new File(['private'],'private.txt',{type:'text/plain'})]}});
    await screen.findByText(/private.txt/);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(state.fetcher.mock.calls.filter(([url,options])=>String(url).endsWith('/attachments')&&options?.method==='POST')).toHaveLength(1);
  });

  it('confirms a committed manuscript upload after its response is lost',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:5,payload:{title:'Saved title',abstract:'Saved abstract'}},{lostMainUpload:true});
    await press(/Saved title · Step 5/);await step(5);
    fireEvent.change(screen.getByLabelText(/Select manuscript file/),{target:{files:[new File(['data'],'source.txt',{type:'text/plain'})]}});
    await press('Upload manuscript');
    await screen.findByText('Manuscript upload confirmed.');
    expect(state.upload).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem('gsub:pending-manuscript-upload:abc:42')).toBeNull();
  });

  it('confirms an NFC receipt for a decomposed selected filename',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:5,payload:{title:'Saved title',abstract:'Saved abstract'}},{normalizedReceipt:true});
    await press(/Saved title · Step 5/);await step(5);
    fireEvent.change(screen.getByLabelText(/Select manuscript file/),{target:{files:[new File(['data'],'Re\u0301sume\u0301.txt',{type:'text/plain'})]}});
    await press('Upload manuscript');
    await screen.findByText('Manuscript upload confirmed.');
    expect(state.upload).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem('gsub:pending-manuscript-upload:abc:42')).toBeNull();
  });

  it('recovers a persisted manuscript request after reopening',async()=>{
    const pending={id:'synthetic-request-id',name:'source.txt',size:4,sha256:'a'.repeat(64)};
    window.localStorage.setItem('gsub:pending-manuscript-upload:abc:42',JSON.stringify(pending));
    const state=fixture({id:'abc',revision:3,current_step:5,payload:{title:'Saved title',abstract:'Saved abstract'}},{currentVersion:{is_current:true,filename:'stored.txt',original_filename:'source.txt'},existingReceipt:{request_id:pending.id,manuscript_id:42,original_filename:pending.name,size:pending.size,sha256:pending.sha256,is_current:true}});
    await press(/Saved title · Step 5/);
    await screen.findByText('Manuscript upload confirmed.');
    expect(state.upload).not.toHaveBeenCalled();
    expect(window.localStorage.getItem('gsub:pending-manuscript-upload:abc:42')).toBeNull();
  });

  it('keeps confirmed legacy uploads available when the recovery migration is absent',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:5,payload:{title:'Saved title',abstract:'Saved abstract'}},{legacyRecovery:true});
    await press(/Saved title · Step 5/);await step(5);
    fireEvent.change(screen.getByLabelText(/Select manuscript file/),{target:{files:[new File(['data'],'source.txt',{type:'text/plain'})]}});
    await press('Upload manuscript');await screen.findByText('Manuscript upload confirmed.');
    expect(state.upload).toHaveBeenCalledTimes(1);
    expect(state.upload.mock.calls[0][2]).toBeUndefined();
  });

  it('does not automatically retry an uncertain legacy upload',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:5,payload:{title:'Saved title',abstract:'Saved abstract'}},{legacyRecovery:true,legacyFailure:true});
    await press(/Saved title · Step 5/);await step(5);
    fireEvent.change(screen.getByLabelText(/Select manuscript file/),{target:{files:[new File(['data'],'source.txt',{type:'text/plain'})]}});
    await press('Upload manuscript');await screen.findByRole('alert');
    expect(screen.getByRole('button',{name:'Clear checked pending upload'})).toBeTruthy();
    await press('Upload manuscript');
    expect(state.upload).toHaveBeenCalledTimes(1);
  });

  it('does not confuse same-name same-size files with different content on retry',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:5,payload:{title:'Saved title',abstract:'Saved abstract'}});
    await press(/Saved title · Step 5/);await step(5);
    const digest=Array.from(new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode('data'))),byte=>byte.toString(16).padStart(2,'0')).join('');
    window.localStorage.setItem('gsub:pending-manuscript-upload:abc:42',JSON.stringify({id:'test-request',name:'source.txt',size:4,sha256:digest}));
    fireEvent.change(screen.getByLabelText(/Select manuscript file/),{target:{files:[new File(['diff'],'source.txt',{type:'text/plain'})]}});
    await press('Upload manuscript');
    expect((await screen.findByRole('alert')).textContent).toMatch(/Reselect the same file/);
    expect(state.upload).not.toHaveBeenCalled();
  });

  it('does not start an upload when recovery state cannot be persisted',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:5,payload:{title:'Saved title',abstract:'Saved abstract'}});
    await press(/Saved title · Step 5/);await step(5);
    vi.stubGlobal('localStorage',{getItem:()=>null,setItem:()=>{throw Error('unavailable');},removeItem:()=>{},clear:()=>{}});
    fireEvent.change(screen.getByLabelText(/Select manuscript file/),{target:{files:[new File(['data'],'source.txt',{type:'text/plain'})]}});
    await press('Upload manuscript');
    expect((await screen.findByRole('alert')).textContent).toMatch(/recovery information could not be saved/);
    expect(state.upload).not.toHaveBeenCalled();
    expect(screen.queryByText('Manuscript upload confirmed.')).toBeNull();
  });

  it('does not upload when secure file hashing is unavailable',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:5,payload:{title:'Saved title',abstract:'Saved abstract'}});
    await press(/Saved title · Step 5/);await step(5);
    vi.stubGlobal('crypto',{randomUUID:()=>webcrypto.randomUUID()});
    fireEvent.change(screen.getByLabelText(/Select manuscript file/),{target:{files:[new File(['data'],'source.txt',{type:'text/plain'})]}});
    await press('Upload manuscript');
    expect((await screen.findByRole('alert')).textContent).toMatch(/Secure file verification is unavailable/);
    expect(state.upload).not.toHaveBeenCalled();
  });

  it('rejects malformed persisted recovery state without uploading',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:5,payload:{title:'Saved title',abstract:'Saved abstract'}});
    window.localStorage.setItem('gsub:pending-manuscript-upload:abc:42','expired or corrupt');
    await press(/Saved title · Step 5/);await step(5);
    expect((await screen.findByRole('alert')).textContent).toMatch(/cannot be read safely/);
    expect(state.upload).not.toHaveBeenCalled();
  });

  it.each(['storage','crypto'])('does not submit when %s recovery is unavailable',async capability=>{
    const state=fixture({id:'abc',revision:3,current_step:10,payload:{title:'Saved title',abstract:'Saved abstract'}});
    await press(/Saved title · Step 10/);await step(10);await press('Next');await screen.findByText('Review and submit');
    if(capability==='storage')vi.stubGlobal('localStorage',{getItem:()=>null,setItem:()=>{throw Error('unavailable');},removeItem:()=>{},clear:()=>{}});
    else vi.stubGlobal('crypto',{});
    await press('Submit manuscript');
    expect((await screen.findByRole('alert')).textContent).toMatch(/recovery information could not be saved/);
    expect(screen.queryByText('Submission successful')).toBeNull();
    expect(state.fetcher.mock.calls.filter(([url,options])=>String(url).includes('/submit')&&options?.method==='POST')).toHaveLength(0);
  });

  it('ignores rapid repeated submit clicks',async()=>{
    const state=fixture({id:'abc',revision:3,current_step:10,payload:{title:'Saved title',abstract:'Saved abstract'}});
    await press(/Saved title · Step 10/);await step(10);await press('Next');await screen.findByText('Review and submit');
    const button=screen.getByRole('button',{name:'Submit manuscript'});
    fireEvent.click(button);fireEvent.click(button);
    await screen.findByText('Submission successful');
    expect(state.fetcher.mock.calls.filter(([url,options])=>String(url).includes('/submit')&&options?.method==='POST')).toHaveLength(1);
  });

  it('does not display submission success when a resumed manuscript has another status',async()=>{
    fixture({id:'abc',revision:3,current_step:10,payload:{title:'Saved title',abstract:'Saved abstract'}},{manuscriptStatus:'revision_required'});
    await press(/Saved title · Step 10/);
    expect(await screen.findByText('This manuscript is no longer a draft. Open it to see its current status.')).toBeTruthy();
    expect(screen.queryByText('Submission successful')).toBeNull();
  });

  it('associates an invalid file message with the manuscript file input',async()=>{
    fixture({id:'abc',revision:3,current_step:5,payload:{title:'Saved title',abstract:'Saved abstract'}});
    await press(/Saved title · Step 5/);await step(5);
    const input=screen.getByLabelText(/Select manuscript file/);
    fireEvent.change(input,{target:{files:[new File(['bad'],'not-supported.exe')]}});
    await press('Upload manuscript');
    await waitFor(()=>expect(input.getAttribute('aria-invalid')).toBe('true'));
    expect(document.getElementById(input.getAttribute('aria-describedby')).textContent).toContain('PDF, DOCX, DOC or TXT');
  });
});
