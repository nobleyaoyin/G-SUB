import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import SubmissionWizard from './SubmissionWizard';

afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks()});
const manuscript={manuscript_id:12,title:'Synthetic draft',abstract:'Synthetic abstract',has_pdf:true,file_type:'txt'};
const props=(overrides={})=>({initialManuscript:manuscript,token:'synthetic-token',onClose:vi.fn(),onCreateDraft:vi.fn(),onUpdateDraft:vi.fn(),onUploadFile:vi.fn(),onSubmitDraft:vi.fn(),...overrides});

it('shows authoritative current version and offers authorized version downloads',async()=>{
 const calls=vi.fn(async url=>url.endsWith('/versions')?{ok:true,json:async()=>[{filename:'old-storage.txt',original_filename:'earlier.txt',version_id:'old-id',is_current:false,size_bytes:3},{filename:'current-storage.txt',original_filename:'current.txt',version_id:'current-id',version_number:3,is_current:true,size_bytes:4}]}:{ok:true,blob:async()=>new Blob(['old'])});
 vi.stubGlobal('fetch',calls);vi.stubGlobal('URL',{...URL,createObjectURL:vi.fn(()=> 'blob:synthetic'),revokeObjectURL:vi.fn()});
 const downloads=[];
 vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(){downloads.push(this.download)});
 const p=props({onDownloadCurrent:vi.fn()});render(<SubmissionWizard {...p}/>);
 expect(await screen.findByText('Current filename: current.txt')).toBeTruthy();
 expect(screen.getByText('Format: TXT')).toBeTruthy();expect(screen.getByText('Version: 3')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Download Current File'}));expect(p.onDownloadCurrent).toHaveBeenCalledWith(12);
 const history=screen.getByRole('region',{name:'Manuscript file versions'});
 fireEvent.click(within(history).getAllByRole('button',{name:'Download version'})[0]);
 await waitFor(()=>expect(calls.mock.calls.some(([url,options])=>String(url).endsWith('/manuscripts/12/versions/old-storage.txt') && options.headers.Authorization==='Bearer synthetic-token')).toBe(true));
 await waitFor(()=>expect(downloads).toEqual(['earlier.txt']));
 expect(calls.mock.calls[0][1].headers.Authorization).toBe('Bearer synthetic-token');
});

it('keeps unknown version evidence unavailable and blocks navigation with unsaved document edits',()=>{
 const p=props({documentDirty:true,renderDocumentEditor:()=> <p>Editor open</p>});
 render(<SubmissionWizard {...p}/>);
 expect(screen.getByText('Current filename: Original filename unavailable')).toBeTruthy();expect(screen.getByText('Version: Unavailable')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Continue to Review'}));
 expect(screen.getByRole('alert').textContent).toContain('Save or close the document editor');
 expect(screen.queryByRole('button',{name:'Submit Manuscript'})).toBeNull();
});

it('keeps all supported replacements in Step 2 and submits only after review',async()=>{
 const p=props({token:null,onUploadFile:vi.fn(async()=>true),onSubmitDraft:vi.fn(async()=>true)});
 render(<SubmissionWizard {...p}/>);
 expect(screen.queryByRole('button',{name:'Submit Manuscript'})).toBeNull();
 const file=new File(['synthetic'],'replacement.doc',{type:'application/msword'});
 fireEvent.change(screen.getByLabelText(/Select a Replacement File/),{target:{files:[file]}});
 fireEvent.click(screen.getByRole('button',{name:'Upload Replacement File'}));
 await screen.findByRole('heading',{name:'Review Your Submission'});
 expect(p.onUploadFile).toHaveBeenCalledWith(12,file);
 fireEvent.click(screen.getByRole('button',{name:'Submit Manuscript'}));
 await screen.findByRole('heading',{name:'Submission Complete'});expect(p.onSubmitDraft).toHaveBeenCalledWith(12);
});

it('does not duplicate the current download in previous versions',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[{filename:'only.txt',is_current:true,size_bytes:4}]})));
 render(<SubmissionWizard {...props({onDownloadCurrent:vi.fn()})}/>);
 expect(await screen.findByText('No previous versions recorded.')).toBeTruthy();
 expect(screen.getAllByRole('button',{name:'Download Current File'})).toHaveLength(1);
 expect(screen.queryByRole('button',{name:'Download version'})).toBeNull();
});


it('uses neutral labels when original names are not recorded and keeps storage identifiers out of view',async()=>{
 const storageId='d1533d5dc86f4521b1e0e2e3321db643';
 vi.stubGlobal('fetch',vi.fn(async url=>url.endsWith('/versions')?{ok:true,json:async()=>[{filename:`${storageId}.docx`,version_id:storageId,is_current:true,size_bytes:32},{filename:'a0b1c2d3e4f567890123456789abcdef.pdf',is_current:false,size_bytes:99}]}:{ok:true,blob:async()=>new Blob(['synthetic'])}));
 vi.stubGlobal('URL',{...URL,createObjectURL:vi.fn(()=> 'blob:synthetic'),revokeObjectURL:vi.fn()});
 const downloads=[];vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(){downloads.push(this.download)});
 render(<SubmissionWizard {...props({initialManuscript:{...manuscript,file_type:'docx'}})}/>);
 expect(await screen.findByText('Current filename: Original filename unavailable')).toBeTruthy();
 expect(await screen.findByText('Previous document')).toBeTruthy();
 expect(screen.getByText('PDF · 99 bytes')).toBeTruthy();
 expect(screen.queryByText(/Version unavailable/)).toBeNull();
 expect(document.body.textContent).not.toContain(storageId);
 expect(document.body.textContent).not.toContain('a0b1c2d3e4f567890123456789abcdef');
 fireEvent.click(screen.getByRole('button',{name:'Download version'}));
 await waitFor(()=>expect(downloads).toEqual(['previous-document.pdf']));
});

it('does not apply a remembered upload name to a different current version',async()=>{
 let requestCount=0;
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/versions')?(++requestCount===1?[{filename:'old-storage.txt',version_id:'old',is_current:true,size_bytes:1}]:[{filename:'different-storage.txt',version_id:'different',is_current:true,size_bytes:1}]):[]})));
 const p=props({onUploadFile:vi.fn(async()=>({versionId:'uploaded',filename:'uploaded-storage.txt'}))});
 render(<SubmissionWizard {...p}/>);
 await screen.findByText('Current filename: Original filename unavailable');
 fireEvent.change(screen.getByLabelText(/Select a Replacement File/),{target:{files:[new File(['x'],'my-upload.txt')]}});
 fireEvent.click(screen.getByRole('button',{name:'Upload Replacement File'}));
 await screen.findByRole('heading',{name:'Review Your Submission'});
 expect(screen.getByText('my-upload.txt')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'← Previous'}));
 await waitFor(()=>expect(requestCount).toBe(2));
 expect(await screen.findByText('Current filename: Original filename unavailable')).toBeTruthy();
 expect(screen.queryByText('my-upload.txt')).toBeNull();
 expect(document.body.textContent).not.toContain('different-storage');
});
