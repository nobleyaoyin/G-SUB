import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import AuthorDashboard from "./AuthorDashboard";

vi.mock("./NotificationBell", () => ({ default: () => <div>Notification bell</div> }));
vi.mock("./InitialEditingPanel", () => ({ default: () => <div>Initial editing workflow</div> }));
vi.mock("./AuthorAgreementPanel", () => ({ default: () => <div>Agreement workflow</div> }));
vi.mock("./FinalEditingPanel", () => ({ default: () => <div>Final editing workflow</div> }));
vi.mock("./FormattingPanel", () => ({ default: () => <div>Formatting workflow</div> }));
vi.mock("./ManuscriptProgress", () => ({ default: ({ manuscriptId }) => <div>Progress details #{manuscriptId}</div> }));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('places private notes before progress and preserves input across disclosure toggles', async () => {
  const item={manuscript_id:12,title:'Private draft',abstract:'Synthetic',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,status:200,headers:new Headers({'content-type':'application/json'}),json:async()=>String(url).includes('/notes') ? [] : [item]})));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Private draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const summary=screen.getByText('Private Notes');
  const details=summary.closest('details');
  expect(summary.compareDocumentPosition(screen.getByText('Progress details #12')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(summary);
  const note=within(details).getByLabelText('New note');
  fireEvent.change(note,{target:{value:'Private unsaved note'}});
  fireEvent.click(summary);
  fireEvent.click(summary);
  expect(within(details).getByLabelText('New note').value).toBe('Private unsaved note');
  expect(screen.queryByText('Comments (Staff Shared)')).toBeNull();
  expect(screen.getByRole('button',{name:'Submit Manuscript'})).toBeTruthy();
});

it('uses the manuscript ID for a blank selected title', async () => {
  const item = {manuscript_id: 12, title: ' ', abstract: 'Synthetic', status: 'draft', has_pdf: false, created_at: '2026-01-01'};
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true, headers:new Headers({'content-type':'application/json'}), json:async()=>[item]})));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button', {name:'Open manuscript'}));
  expect(screen.getByRole('heading', {name:'Manuscript #12'})).toBeTruthy();
  expect(within(screen.getByRole('heading', {name:'Manuscript #12'}).closest('[data-workspace=selected]')).getAllByText('Manuscript #12')).toHaveLength(1);
  expect(screen.queryByRole('button', {name:'+ New Submission'})).toBeNull();
});

it("keeps draft actions and progress above the workflow panels", async () => {
  const manuscript = { manuscript_id: 12, title: "Synthetic draft", abstract: "Synthetic", status: "draft", has_pdf: true, created_at: "2026-01-01" };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, headers: new Headers({ "content-type": "application/json" }), json: async () => [manuscript] })));
  render(<AuthorDashboard user={{ name: "Synthetic" }} token="synthetic" />);
  const title = await screen.findByText("Synthetic draft");
  let card = title.closest(".manuscript-card");
  expect(card).toBeTruthy();
  fireEvent.click(within(card).getByRole("button", { name: "Open manuscript" }));
  card = screen.getByText('Synthetic draft').closest('.manuscript-card');
  expect(card.closest('[data-workspace=selected]')).toBeTruthy();
  expect(within(card).getByText('Complete your draft and submit it when ready.')).toBeTruthy();
  for (const name of ["Upload File", "Download File", "Edit Title", "Edit Abstract", "Submit Manuscript"]) expect(within(card).getByRole("button", { name })).toBeTruthy();
  const progress = screen.getByText("Progress details #12");
  const wizard = progress.closest(".author-workflows");

  expect(wizard).toBeTruthy();
  expect(
    wizard.querySelector(".author-wizard-progress").contains(progress)
  ).toBe(true);
  expect(wizard.querySelector(".author-wizard-navigation")).toBeNull();
  expect(wizard.querySelector(".author-wizard-footer")).toBeNull();
  expect(wizard.querySelector(".author-wizard-header")).toBeNull();
  fireEvent.click(within(card).getByRole("button", { name: "Back to Manuscripts" }));
  expect(screen.queryByText("Progress details #12")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "+ New Submission" }));
  expect(screen.getByLabelText(/Manuscript Title/)).toBeTruthy();
});

it('selects distinct manuscripts without mixing their timelines', async () => {
  const items = [12,13].map(id => ({ manuscript_id:id,title:`Synthetic ${id}`,abstract:`Abstract ${id}`,status:'draft',has_pdf:true,created_at:'2026-01-01' }));
  vi.stubGlobal('fetch',vi.fn(async () => ({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>items})));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  const first = (await screen.findByText('Synthetic 12')).closest('.manuscript-card');
  fireEvent.click(within(first).getByRole('button',{name:'Open manuscript'}));
  expect(screen.getByText('Progress details #12')).toBeTruthy();
  expect(screen.queryByText('Synthetic 13')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Back to Manuscripts'}));
  const second = screen.getByText('Synthetic 13').closest('.manuscript-card');
  fireEvent.click(within(second).getByRole('button',{name:'Open manuscript'}));
  expect(screen.getByText('Progress details #13')).toBeTruthy();
  expect(screen.queryByText('Progress details #12')).toBeNull();
  expect(screen.queryByRole('button',{name:/refresh/i})).toBeNull();
});

it('keeps the same card and information during upload and clears its busy state', async () => {
  const manuscript = {manuscript_id:12,title:'Synthetic draft',abstract:'Original abstract',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  let finishUpload;
  const json = data => ({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
  vi.stubGlobal('fetch',vi.fn(url => url.endsWith('/upload') ? new Promise(resolve => {finishUpload=resolve}) : Promise.resolve(json(url.includes('/notes') ? [] : url.endsWith('/manuscripts/12') ? manuscript : [manuscript]))));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Synthetic draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const card=screen.getByText('Synthetic draft').closest('.manuscript-card');
  const input=card.querySelector('input[type=file]');
  fireEvent.click(within(card).getByRole('button',{name:'Upload File'}));
  fireEvent.change(input,{target:{files:[new File(['hello'],'new.txt',{type:'text/plain'})]}});
  fireEvent.change(input,{target:{files:[new File(['duplicate'],'duplicate.txt',{type:'text/plain'})]}});
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/upload'))).toHaveLength(1);
  expect(screen.getByText('Original abstract')).toBeTruthy();
  expect(within(card).getByRole('button',{name:'Uploading...'}).disabled).toBe(true);
  finishUpload(json({}));
  await waitFor(() => expect(within(card).getByRole('button',{name:'Upload File'}).disabled).toBe(false));
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/manuscripts/my'))).toHaveLength(1);
  expect(screen.getByText('Synthetic draft').closest('.manuscript-card')).toBe(card);
  expect(screen.getByText('Original abstract')).toBeTruthy();
  fireEvent.click(within(card).getByRole('button',{name:'Back to Manuscripts'}));
  expect(screen.queryByText('Progress details #12')).toBeNull();
});

it('clears the picker guard on cancellation without treating it as an edit', async () => {
  const item={manuscript_id:12,title:'Picker draft',abstract:'Original',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>[item]})));
  const confirm = vi.spyOn(window,'confirm');
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Picker draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const card=screen.getByText('Picker draft').closest('.manuscript-card');
  fireEvent.click(within(card).getByRole('button',{name:'Upload File'}));
  fireEvent(card.querySelector('input[type=file]'),new Event('cancel',{bubbles:true}));
  fireEvent.click(within(card).getByRole('button',{name:'Back to Manuscripts'}));
  expect(confirm).not.toHaveBeenCalled();
  confirm.mockRestore();
});

it('re-enables download after an API failure', async () => {
  const item={manuscript_id:12,title:'Download draft',abstract:'Original',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  vi.stubGlobal('fetch',vi.fn(async url => url.includes('/notes')
    ? {ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>[]}
    : url.endsWith('/download')
      ? {ok:false,headers:new Headers({'content-type':'application/json'}),json:async()=>({detail:'Download unavailable'})}
      : {ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>[item]}));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Download draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByRole('button',{name:'Download File'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Download unavailable');
  expect(screen.getByRole('button',{name:'Download File'}).disabled).toBe(false);
});

it('ignores a list read started before an upload completed', async () => {
  const item={manuscript_id:12,title:'Current draft',abstract:'Current',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  const json = data => ({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
  let reads=0, finishOld;
  vi.stubGlobal('fetch',vi.fn(url => {
    if (url.includes('/notes')) return Promise.resolve(json([]));
    if (url.endsWith('/upload')) return Promise.resolve(json({}));
    if (url.endsWith('/manuscripts/12')) return Promise.resolve(json(item));
    reads++;
    if (reads===2) return new Promise(resolve=>{finishOld=resolve});
    return Promise.resolve(json([item]));
  }));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  await screen.findByText('Current draft');
  fireEvent.focus(window);
  await waitFor(()=>expect(reads).toBe(2));
  fireEvent.click(screen.getByRole('button',{name:'Open manuscript'}));
  const card=screen.getByText('Current draft').closest('.manuscript-card');
  fireEvent.change(card.querySelector('input[type=file]'),{target:{files:[new File(['hello'],'new.txt',{type:'text/plain'})]}});
  await screen.findByText(/file uploaded successfully/);
  finishOld(json([{...item,title:'Stale draft'}]));
  await waitFor(()=>expect(screen.queryByText('Stale draft')).toBeNull());
  expect(screen.getByText('Current draft')).toBeTruthy();
});

it.each(['paper.pdf', 'paper.docx', 'paper.txt'])('revalidates only the uploaded manuscript after %s', async filename => {
  const items=[12,13].map(id=>({manuscript_id:id,title:`Draft ${id}`,abstract:`Abstract ${id}`,status:'draft',has_pdf:true,created_at:'2026-01-01'}));
  const json=data=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
  const fetchMock=vi.fn(async url=>json(url.endsWith('/upload') ? {} : url.endsWith('/manuscripts/12') ? items[0] : items));
  vi.stubGlobal('fetch',fetchMock);
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  const first=(await screen.findByText('Draft 12')).closest('.manuscript-card');
  expect(screen.getByText('Draft 13')).toBeTruthy();
  fireEvent.click(within(first).getByRole('button',{name:'Open manuscript'}));
  const card=screen.getByText('Draft 12').closest('.manuscript-card');
  fireEvent.change(card.querySelector('input[type=file]'),{target:{files:[new File(['synthetic'],filename)]}});
  await screen.findByText(/file uploaded successfully/);
  expect(fetchMock.mock.calls.filter(([url])=>url.endsWith('/manuscripts/my'))).toHaveLength(1);
  expect(fetchMock.mock.calls.filter(([url])=>url.endsWith('/manuscripts/12'))).toHaveLength(1);
  expect(screen.getByText('Draft 12').closest('.manuscript-card')).toBe(card);
  const editButton = within(card).getByRole('button', {
    name: 'Edit Title'
  });
  expect(editButton).toBeTruthy();

  fireEvent.click(editButton);

  expect(within(card).getByLabelText('Title')).toBeTruthy();
  fireEvent.click(within(card).getByRole('button',{name:'Edit Abstract'}));
  expect(within(card).getByLabelText('Abstract')).toBeTruthy();

  // Cancel editing before navigating back.
  fireEvent.click(within(card).getByRole('button',{name:'Cancel Title'}));
  fireEvent.click(within(card).getByRole('button',{name:'Cancel Abstract'}));

  fireEvent.click(within(card).getByRole('button',{name:'Back to Manuscripts'}));
  expect(screen.getByText('Draft 13')).toBeTruthy();
});

it.each(['failure', 'wrong manuscript', 'incomplete response'])('keeps prior details if upload revalidation returns %s', async kind => {
  const item={manuscript_id:12,title:'Safe draft',abstract:'Keep this content',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  const json=data=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
  vi.stubGlobal('fetch',vi.fn(async url => url.endsWith('/upload') ? json({}) : url.endsWith('/manuscripts/12')
    ? (kind === 'failure' ? {ok:false} : kind === 'incomplete response' ? json({manuscript_id:12}) : json({...item,manuscript_id:13,title:'Wrong manuscript'})) : json([item])));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Safe draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const card=screen.getByText('Safe draft').closest('.manuscript-card');
  fireEvent.change(card.querySelector('input[type=file]'),{target:{files:[new File(['synthetic'],'paper.txt')]}});
  await screen.findByText(/could not be refreshed/);
  expect(screen.getByText('Keep this content')).toBeTruthy();
  expect(screen.queryByText('Wrong manuscript')).toBeNull();
  expect(within(card).getByRole('button',{name:'Upload File'}).disabled).toBe(false);
});

it('keeps the same upload button through upload, revalidation, success and retry', async () => {
  const item={manuscript_id:12,title:'Button draft',abstract:'Unchanged',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  const json=data=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
  let finishUpload, finishDetails;
  const fetchMock=vi.fn(url=> {
    if (url.endsWith('/upload')) return new Promise(resolve=>{finishUpload=resolve});
    if (url.endsWith('/manuscripts/12')) return new Promise(resolve=>{finishDetails=resolve});
    return Promise.resolve(json([item]));
  });
  vi.stubGlobal('fetch',fetchMock);
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Button draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const card=screen.getByText('Button draft').closest('.manuscript-card');
  const button=within(card).getByRole('button',{name:'Upload File'});
  const observed=['Upload File'];
  const observer=new MutationObserver(()=>observed.push(button.textContent.trim()));
  observer.observe(button,{subtree:true,childList:true,characterData:true});
  const select=()=>fireEvent.change(card.querySelector('input[type=file]'),{target:{files:[new File(['x'],'paper.txt')]}});
  select();
  expect(button.textContent.trim()).toBe('Uploading...');
  finishUpload(json({}));
  await waitFor(()=>expect(finishDetails).toBeTypeOf('function'));
  expect(button.textContent.trim()).toBe('Uploading...');
  expect(button.isConnected).toBe(true);
  finishDetails(json(item));
  await waitFor(()=>expect(button.textContent.trim()).toBe('Upload File'));
  expect(within(card).getByRole('button',{name:'Upload File'})).toBe(button);
  expect(screen.getByText(/file uploaded successfully/)).toBeTruthy();
  select();
  expect(button.textContent.trim()).toBe('Uploading...');
  finishUpload({ok:false,headers:new Headers({'content-type':'application/json'}),json:async()=>({detail:'Upload failed'})});
  await waitFor(()=>expect(button.textContent.trim()).toBe('Upload File'));
  expect(button.disabled).toBe(false);
  finishDetails=undefined;
  select();
  expect(button.textContent.trim()).toBe('Uploading...');
  finishUpload(json({}));
  await waitFor(()=>expect(finishDetails).toBeTypeOf('function'));
  finishDetails(json(item));
  await waitFor(()=>expect(button.textContent.trim()).toBe('Upload File'));
  expect(fetchMock.mock.calls.filter(([url])=>url.endsWith('/upload'))).toHaveLength(3);
  expect(observed.every(label=>['Upload File','Uploading...'].includes(label))).toBe(true);
  observer.disconnect();
});


it('keeps disabled submission distinct from file upload and describes all supported formats', async () => {
  const item = {manuscript_id: 12, title: 'No file draft', abstract: 'Synthetic', status: 'draft', has_pdf: false, created_at: '2026-01-01'};
  vi.stubGlobal('fetch', vi.fn(async () => ({ok: true, headers: new Headers({'content-type': 'application/json'}), json: async () => [item]})));
  render(<AuthorDashboard user={{name: 'Synthetic'}} token="synthetic" />);
  const initial = (await screen.findByText('No file draft')).closest('.manuscript-card');
  fireEvent.click(within(initial).getByRole('button', {name: 'Open manuscript'}));
  const card = screen.getByText('No file draft').closest('.manuscript-card');
  const upload = within(card).getByRole('button', {name: 'Upload File'});
  const submit = within(card).getByRole('button', {name: 'Submit Manuscript'});
  expect(upload.classList.contains('file-upload-control')).toBe(true);
  expect(submit.disabled).toBe(true);
  expect(submit.matches('.manuscript-actions .file-upload-control:disabled')).toBe(false);
  expect(submit.title).toBe('Upload a PDF, DOCX, DOC, or TXT file before submitting');
});


it('returns the actual author workspace through the registered guarded handler', async () => {
  const items = [1, 2].map(id => ({ manuscript_id:id, title:`Paper ${id}`, abstract:`Abstract ${id}`, status:'draft', has_pdf:true, created_at:'2026-01-01' }));
  vi.stubGlobal('fetch', vi.fn(async url => ({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>String(url).includes('/notes') ? [] : items})));
  vi.stubGlobal('confirm', vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true));
  let goBack;
  const register = handler => { goBack = handler; return () => {}; };
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" registerManuscriptReturn={register} />);
  fireEvent.click(within((await screen.findByText('Paper 1')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  expect(screen.getAllByText('Paper 1')).toHaveLength(1);
  expect(screen.queryByText('Paper 2')).toBeNull();
  expect(screen.queryByRole('button',{name:'+ New Submission'})).toBeNull();
  expect(screen.queryByLabelText('Manuscript statistics')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Edit Title'}));
  fireEvent.change(screen.getByLabelText('Title'),{target:{value:'Unsaved title'}});
  act(() => { expect(goBack()).toBe(false); });
  expect(screen.getByLabelText('Title').value).toBe('Unsaved title');
  act(() => { expect(goBack()).toBe(true); });
  expect(screen.getByText('Paper 2')).toBeTruthy();
  fireEvent.click(within(screen.getByText('Paper 2').closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  expect(screen.queryByText('Paper 1')).toBeNull();
  expect(screen.getAllByText('Paper 2')).toHaveLength(1);
});


it('keeps private note input when its disclosure is closed and reopened', async () => {
  const item={manuscript_id:1,title:'Private paper',abstract:'Abstract',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>String(url).includes('/notes')?[]:[item]})));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Private paper')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const summary=screen.getByText('Private Notes');
  fireEvent.click(summary);
  const note=await screen.findByLabelText('New note');
  fireEvent.change(note,{target:{value:'Private unsaved note'}});
  fireEvent.click(summary); fireEvent.click(summary);
  expect(screen.getByLabelText('New note').value).toBe('Private unsaved note');
  expect(screen.queryByText('Comments (Staff Shared)')).toBeNull();
});
