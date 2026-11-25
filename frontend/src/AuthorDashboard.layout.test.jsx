import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import AuthorDashboard from "./AuthorDashboard";

vi.mock("./NotificationBell", () => ({ default: () => <div>Notification bell</div> }));
vi.mock("./InitialEditingPanel", () => ({ default: () => <div>Initial editing workflow</div> }));
vi.mock("./AuthorAgreementPanel", () => ({ default: () => <div>Agreement workflow</div> }));
vi.mock("./FinalEditingPanel", () => ({ default: () => <div>Final editing workflow</div> }));
vi.mock("./FormattingPanel", () => ({ default: () => <div>Formatting workflow</div> }));
vi.mock("./ManuscriptProgress", () => ({ default: ({ manuscriptId, fallbackAction }) => <div><p>{fallbackAction}</p><div>Progress details #{manuscriptId}</div></div> }));

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
  expect(screen.getByRole('button',{name:'Continue Process'})).toBeTruthy();
  expect(screen.queryByRole('button',{name:'Submit Manuscript'})).toBeNull();
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
  for (const name of ["Continue Process", "Edit title", "Edit abstract"]) expect(within(card).getByRole("button", { name })).toBeTruthy();
  expect(within(card).queryByRole("button", { name: "Upload File" })).toBeNull();
  expect(within(card).queryByRole("button", { name: "Download file" })).toBeNull();
  expect(within(card).queryByRole("button", { name: "Submit Manuscript" })).toBeNull();
  const progress = screen.getByText("Progress details #12");
  const wizard = progress.closest(".author-workflows");

  expect(wizard).toBeTruthy();
  expect(
    wizard.querySelector(".author-wizard-progress").contains(progress)
  ).toBe(true);
  expect(wizard.querySelector(".author-wizard-navigation")).toBeNull();
  expect(wizard.querySelector(".author-wizard-footer")).toBeNull();
  expect(wizard.querySelector(".author-wizard-header")).toBeNull();
  fireEvent.click(within(card).getByRole("button", { name: "Back to manuscripts" }));
  expect(screen.queryByText("Progress details #12")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "+ New Submission" }));
  expect(screen.getByRole('heading',{name:'Prepare your submission'})).toBeTruthy();
});

it('selects distinct manuscripts without mixing their timelines', async () => {
  const items = [12,13].map(id => ({ manuscript_id:id,title:`Synthetic ${id}`,abstract:`Abstract ${id}`,status:'draft',has_pdf:true,created_at:'2026-01-01' }));
  vi.stubGlobal('fetch',vi.fn(async () => ({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>items})));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  const first = (await screen.findByText('Synthetic 12')).closest('.manuscript-card');
  fireEvent.click(within(first).getByRole('button',{name:'Open manuscript'}));
  expect(screen.getByText('Progress details #12')).toBeTruthy();
  expect(screen.queryByText('Synthetic 13')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
  const second = screen.getByText('Synthetic 13').closest('.manuscript-card');
  fireEvent.click(within(second).getByRole('button',{name:'Open manuscript'}));
  expect(screen.getByText('Progress details #13')).toBeTruthy();
  expect(screen.queryByText('Progress details #12')).toBeNull();
  expect(screen.queryByRole('button',{name:/refresh/i})).toBeNull();
});

async function openWizardUpload(card) {
  fireEvent.click(within(card).getByRole('button',{name:'Continue Process'}));
  if (screen.queryByRole('heading',{name:'Review Your Submission'})) fireEvent.click(screen.getByRole('button',{name:'← Previous'}));
  return within(document.querySelector('.submission-wizard'));
}

it('keeps wizard information and blocks duplicate upload while busy', async () => {
  const item={manuscript_id:12,title:'Synthetic draft',abstract:'Original abstract',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  let finishUpload;
  const json=data=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
  const fetchMock=vi.fn(url=>url.endsWith('/upload') ? new Promise(resolve=>{finishUpload=resolve}) : Promise.resolve(json(url.includes('/notes')?[]:url.endsWith('/manuscripts/12')?item:[item])));
  vi.stubGlobal('fetch',fetchMock);
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Synthetic draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const wizard=await openWizardUpload(screen.getByText('Synthetic draft').closest('.manuscript-card'));
  fireEvent.change(wizard.getByLabelText(/Select a Replacement File/),{target:{files:[new File(['hello'],'new.txt')]}});
  fireEvent.click(wizard.getByRole('button',{name:/^Upload (Replacement )?File$/}));
  expect(wizard.getByRole('button',{name:'Uploading...'}).disabled).toBe(true);
  expect(wizard.getByRole('button',{name:'Close submission wizard'}).disabled).toBe(true);
  expect(wizard.getByText('Synthetic draft')).toBeTruthy();
  expect(fetchMock.mock.calls.filter(([url])=>url.endsWith('/upload'))).toHaveLength(1);
  finishUpload(json({}));
  await screen.findByRole('heading',{name:'Review Your Submission'});
  expect(wizard.getByText('Original abstract')).toBeTruthy();
  expect(fetchMock.mock.calls.filter(([url])=>url.endsWith('/manuscripts/my'))).toHaveLength(1);
});

it('closes the wizard after an empty picker selection without treating it as an edit', async () => {
  const item={manuscript_id:12,title:'Picker draft',abstract:'Original',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>[item]})));
  const confirm=vi.spyOn(window,'confirm');
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Picker draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const wizard=await openWizardUpload(screen.getByText('Picker draft').closest('.manuscript-card'));
  fireEvent.change(wizard.getByLabelText(/Select a Replacement File/),{target:{files:[]}});
  fireEvent.click(wizard.getByRole('button',{name:'Close submission wizard'}));
  expect(confirm).not.toHaveBeenCalled();
  expect(screen.getByRole('button',{name:'Continue Process'})).toBeTruthy();
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
  fireEvent.click(screen.getByRole('button',{name:'Continue Process'}));
  fireEvent.click(screen.getByRole('button',{name:'Download Current File'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Download unavailable');
  expect(screen.getByRole('button',{name:'Download Current File'}).disabled).toBe(false);
});

it('ignores a list read started before a wizard upload completed', async () => {
  const item={manuscript_id:12,title:'Current draft',abstract:'Current',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  const json=data=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
  let reads=0, finishOld;
  vi.stubGlobal('fetch',vi.fn(url=>{
    if(url.includes('/notes')) return Promise.resolve(json([]));
    if(url.endsWith('/upload')) return Promise.resolve(json({}));
    if(url.endsWith('/manuscripts/12')) return Promise.resolve(json(item));
    reads++; if(reads===2) return new Promise(resolve=>{finishOld=resolve});
    return Promise.resolve(json([item]));
  }));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  await screen.findByText('Current draft');fireEvent.focus(window);await waitFor(()=>expect(reads).toBe(2));
  fireEvent.click(screen.getByRole('button',{name:'Open manuscript'}));
  const wizard=await openWizardUpload(screen.getByText('Current draft').closest('.manuscript-card'));
  fireEvent.change(wizard.getByLabelText(/Select a Replacement File/),{target:{files:[new File(['hello'],'new.txt')]}});
  fireEvent.click(wizard.getByRole('button',{name:/^Upload (Replacement )?File$/}));
  await screen.findByRole('heading',{name:'Review Your Submission'});
  await act(async()=>finishOld(json([{...item,title:'Stale draft'}])));
  fireEvent.click(wizard.getByRole('button',{name:'Close submission wizard'}));
  expect(screen.queryByText('Stale draft')).toBeNull();expect(screen.getByText('Current draft')).toBeTruthy();
});

it.each(['paper.pdf','paper.docx','paper.doc','paper.txt'])('revalidates only the uploaded manuscript after wizard replacement %s', async filename => {
  const items=[12,13].map(id=>({manuscript_id:id,title:`Draft ${id}`,abstract:`Abstract ${id}`,status:'draft',has_pdf:true,created_at:'2026-01-01'}));
  const json=data=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
  const fetchMock=vi.fn(async url=>json(url.endsWith('/upload') ? {} : url.endsWith('/manuscripts/12') ? items[0] : items));
  vi.stubGlobal('fetch',fetchMock);render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Draft 12')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const wizard=await openWizardUpload(screen.getByText('Draft 12').closest('.manuscript-card'));
  fireEvent.change(wizard.getByLabelText(/Select a Replacement File/),{target:{files:[new File(['synthetic'],filename)]}});
  fireEvent.click(wizard.getByRole('button',{name:/^Upload (Replacement )?File$/}));await screen.findByRole('heading',{name:'Review Your Submission'});
  expect(fetchMock.mock.calls.filter(([url])=>url.endsWith('/manuscripts/my'))).toHaveLength(1);
  expect(fetchMock.mock.calls.filter(([url])=>url.endsWith('/manuscripts/12'))).toHaveLength(1);
  fireEvent.click(wizard.getByRole('button',{name:'Close submission wizard'}));
  const card=screen.getByText('Draft 12').closest('.manuscript-card');
  expect(within(card).getByRole('button',{name:'Edit title'})).toBeTruthy();
  fireEvent.click(within(card).getByRole('button',{name:'Back to manuscripts'}));expect(screen.getByText('Draft 13')).toBeTruthy();
});

it.each(['failure','wrong manuscript','incomplete response'])('keeps prior draft if wizard upload revalidation returns %s', async kind => {
  const item={manuscript_id:12,title:'Safe draft',abstract:'Keep this content',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  const json=data=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
  vi.stubGlobal('fetch',vi.fn(async url=>url.endsWith('/upload')?json({}):url.endsWith('/manuscripts/12')?(kind==='failure'?{ok:false}:kind==='incomplete response'?json({manuscript_id:12}):json({...item,manuscript_id:13,title:'Wrong manuscript'})):json([item])));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Safe draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const wizard=await openWizardUpload(screen.getByText('Safe draft').closest('.manuscript-card'));
  fireEvent.change(wizard.getByLabelText(/Select a Replacement File/),{target:{files:[new File(['synthetic'],'paper.txt')]}});
  fireEvent.click(wizard.getByRole('button',{name:/^Upload (Replacement )?File$/}));
  await screen.findByText(/file upload could not be confirmed/i);
  expect(screen.queryByText('Wrong manuscript')).toBeNull();
  expect(wizard.getByRole('button',{name:/^Upload (Replacement )?File$/}).disabled).toBe(false);
  vi.stubGlobal('confirm',vi.fn(()=>true));fireEvent.click(wizard.getByRole('button',{name:'Close submission wizard'}));
  expect(screen.getByText('Keep this content')).toBeTruthy();
});

it('allows retry after a wizard upload fails and keeps the operation single-flight', async () => {
  const item={manuscript_id:12,title:'Retry draft',abstract:'Unchanged',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  const json=data=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>data});
  let finishUpload;
  const fetchMock=vi.fn(url=>url.endsWith('/upload')?new Promise(resolve=>{finishUpload=resolve}):Promise.resolve(json(url.endsWith('/manuscripts/12')?item:[item])));
  vi.stubGlobal('fetch',fetchMock);render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Retry draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const wizard=await openWizardUpload(screen.getByText('Retry draft').closest('.manuscript-card'));
  fireEvent.change(wizard.getByLabelText(/Select a Replacement File/),{target:{files:[new File(['x'],'paper.txt')]}});
  fireEvent.click(wizard.getByRole('button',{name:/^Upload (Replacement )?File$/}));
  expect(wizard.getByRole('button',{name:'Uploading...'}).disabled).toBe(true);
  finishUpload({ok:false,headers:new Headers({'content-type':'application/json'}),json:async()=>({detail:'Upload failed'})});
  await screen.findByText('Upload failed');expect(wizard.getByRole('button',{name:/^Upload (Replacement )?File$/}).disabled).toBe(false);
  fireEvent.click(wizard.getByRole('button',{name:/^Upload (Replacement )?File$/}));finishUpload(json({}));
  await screen.findByRole('heading',{name:'Review Your Submission'});
  expect(fetchMock.mock.calls.filter(([url])=>url.endsWith('/upload'))).toHaveLength(2);
});

it('keeps submission disabled for an empty draft while the wizard describes the supported formats', async () => {
  const item={manuscript_id:12,title:'No file draft',abstract:'Synthetic',status:'draft',has_pdf:false,created_at:'2026-01-01'};
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>[item]})));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('No file draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  const card=screen.getByText('No file draft').closest('.manuscript-card');
  expect(within(card).queryByRole('button',{name:/^Upload (Replacement )?File$/})).toBeNull();
  expect(within(card).queryByRole('button',{name:'Submit Manuscript'})).toBeNull();
  const wizard=await openWizardUpload(card);
  expect(wizard.getByText(/PDF, DOCX, DOC, or TXT/)).toBeTruthy();
  expect(wizard.getByRole('button',{name:/^Upload (Replacement )?File$/}).disabled).toBe(true);
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
  expect(screen.getByLabelText('Manuscript statistics').querySelector('details')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Edit title'}));
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

it('protects an unsaved detail note when continuing a draft in the wizard', async () => {
  const item={manuscript_id:12,title:'Private draft',abstract:'Synthetic',status:'draft',has_pdf:false,created_at:'2026-01-01'};
  vi.stubGlobal('confirm',vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true));
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,status:200,headers:new Headers({'content-type':'application/json'}),json:async()=>String(url).includes('/notes') ? [] : [item]})));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('Private draft')).closest('.manuscript-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByText('Private Notes'));
  fireEvent.change(screen.getByLabelText('New note'),{target:{value:'Keep this note'}});
  fireEvent.click(screen.getByRole('button',{name:'Continue Process'}));
  expect(window.confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText('New note').value).toBe('Keep this note');
  expect(screen.queryByRole('heading',{name:'Continue Manuscript Submission'})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Continue Process'}));
  expect(window.confirm).toHaveBeenCalledTimes(2);
  expect(screen.getByRole('heading',{name:'Continue Manuscript Submission'})).toBeTruthy();
  expect(screen.queryByLabelText('New note')).toBeNull();
});

it('keeps one statistics sidebar and places the abstract above private notes and next step', async () => {
  const item={manuscript_id:12,title:'Synthetic draft',abstract:'A preserved abstract',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>[item]})));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
  const layout=document.querySelector('.author-content-layout');
  expect(layout.classList.contains('has-manuscript-detail')).toBe(true);
  expect(within(layout).getAllByLabelText('Manuscript statistics')).toHaveLength(1);
  const stats=within(layout).getByLabelText('Manuscript statistics');
  expect(stats.parentElement).toBe(layout);
  const summary=within(stats).getByText('Statistics');
  const wasOpen=summary.closest('details').open;
  fireEvent.click(summary); expect(summary.closest('details').open).toBe(!wasOpen);
  fireEvent.click(summary); expect(summary.closest('details').open).toBe(wasOpen);
  expect(screen.queryByText('Stage Threads')).toBeNull();
  const next=screen.getByRole('heading',{name:'Next Step'});
  const abstract=screen.getByRole('region',{name:'Manuscript Abstract'});
  expect(screen.getAllByRole('region',{name:'Manuscript Abstract'})).toHaveLength(1);
  const notes=screen.getByText('Private Notes');
  expect(abstract.compareDocumentPosition(notes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(notes.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const history=screen.getByText('Generation history');
  const progress=screen.getByText('Progress details #12');
  const activity=screen.getByText('Activity Timeline');
  expect(notes.compareDocumentPosition(history) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(history.compareDocumentPosition(progress) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(progress.compareDocumentPosition(activity) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(activity.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(within(abstract).getByText('A preserved abstract')).toBeTruthy();
  expect(screen.getByRole('button',{name:'Continue Process'})).toBeTruthy();
});

it('keeps one statistics sidebar as a sibling of the Author manuscript list', async () => {
  const item={manuscript_id:12,title:'Synthetic list record',abstract:'Synthetic',status:'draft',has_pdf:true,created_at:'2026-01-01'};
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>[item]})));
  render(<AuthorDashboard user={{name:'Synthetic'}} token="synthetic" section="manuscripts" onSectionChange={()=>{}} />);
  await screen.findByText('Synthetic list record');
  const layout=document.querySelector('.author-content-layout');
  expect(layout.classList.contains('has-manuscript-list')).toBe(true);
  const sidebar=within(layout).getByLabelText('Manuscript statistics');
  expect(sidebar.parentElement).toBe(layout);
  expect(layout.querySelector('.author-primary-content').parentElement).toBe(layout);
  expect(within(layout).getAllByLabelText('Manuscript statistics')).toHaveLength(1);
  const summary=within(sidebar).getByText('Statistics');
  const previous=summary.closest('details').open;
  fireEvent.click(summary);expect(summary.closest('details').open).toBe(!previous);
});
