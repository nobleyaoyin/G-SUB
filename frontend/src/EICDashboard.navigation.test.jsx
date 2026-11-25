import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import EICDashboard from './EICDashboard';
import { StrictMode, useEffect } from 'react';
vi.mock('./NotificationBell', () => ({ default: () => null }));
vi.mock('./FormattingPanel', () => ({ default: () => null }));
vi.mock('./BlindReviewPanel', () => ({ default: () => null }));
vi.mock('./ManuscriptProgress', () => ({ default: ({manuscriptId,onProgressChange,onBrowseStage,selectedStage}) => {
  useEffect(() => {
    const status = document.querySelector('.eic-status-badge')?.textContent?.trim().toLowerCase();
    const stage = ({submitted:'Initial Screening','initial scan passed':'Initial Editing',published:'Publication',formatting:'Formatting','ready for peer review':'Peer Review','currently in review':'Peer Review',revised:'Peer Review'})[status] || null;
    onProgressChange?.({manuscript_id:manuscriptId,review_round:1,current_stage:stage,stages:stage ? [{name:stage,state:'current'}] : []});
  },[manuscriptId,onProgressChange]);
  const status = document.querySelector('.eic-status-badge')?.textContent?.trim().toLowerCase();
  const current = ({submitted:'Initial Screening','initial scan passed':'Initial Editing',published:'Publication',formatting:'Formatting','ready for peer review':'Peer Review','currently in review':'Peer Review',revised:'Peer Review'})[status] || null;
  return <nav aria-label="Manuscript stages">{['Submission','Initial Screening','Initial Editing','Peer Review','EIC Decision','Author Agreement','Final Editing','Formatting','Publication'].map(name => <button key={name} aria-current={current === name ? 'step' : undefined} aria-pressed={selectedStage === name} onClick={() => onBrowseStage(name)}>View {name} workspace</button>)}<span>Timeline #{manuscriptId}</span></nav>;
} }));
afterEach(() => { cleanup(); sessionStorage.removeItem('gsub-eic-workspace-v1'); vi.unstubAllGlobals(); });
const overview = id => ({ manuscript:{ manuscript_id:id,title:`Paper ${id}`,status:'submitted',author:'Synthetic',abstract:`Abstract ${id}`,review_round:1 }, review_progress:{can_decide:false}, decisions:[],submissions:[],final_invitations:[],final_workflow_submissions:[],scans:[],invitations:[],confirmations:[],assignments:[],author_agreement:null,final_submissions:[] });
it('restores the selected stage after refresh using an authorized overview read', async () => {
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'submitted'}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>overview(1)};
    return {ok:false,json:async()=>({})};
  }));
  const props={user:{user_id:123,name:'Synthetic'},token:'synthetic'};
  const first=render(<EICDashboard {...props} />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  let nav=await screen.findByRole('navigation',{name:'Manuscript stages'});
  const title=screen.getByRole('heading',{name:'Paper 1'});
  const id=screen.getByText('Manuscript #1');
  const abstract=screen.getByRole('region',{name:'Manuscript Abstract'});
  expect(title.compareDocumentPosition(id) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(id.compareDocumentPosition(abstract) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(abstract.compareDocumentPosition(screen.getByText('Private Notes')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getAllByText('Abstract 1')).toHaveLength(1);
  const sidebar=screen.getByLabelText('Manuscript statistics');
  expect(sidebar.classList.contains('manuscripts-list-sidebar')).toBe(true);
  expect(sidebar.parentElement.querySelector('.manuscripts-list-content').contains(nav)).toBe(true);
  expect(screen.queryByText('Stage Threads')).toBeNull();
  expect(screen.getByText('Private Notes')).toBeTruthy();
  expect(screen.getByText('Comments (Staff Shared)')).toBeTruthy();
  fireEvent.click(within(nav).getByRole('button',{name:/Publication/}));
  await waitFor(()=>expect(JSON.parse(sessionStorage.getItem('gsub-eic-workspace-v1')).stage).toBe('Publication'));
  first.unmount();
  render(<StrictMode><EICDashboard {...props} /></StrictMode>);
  nav=await screen.findByRole('navigation',{name:'Manuscript stages'});
  await waitFor(()=>expect(within(nav).getByRole('button',{name:/Initial Screening/}).getAttribute('aria-current')).toBe('step'));
  expect(within(nav).getByRole('button',{name:/Publication/}).getAttribute('aria-pressed')).toBe('true');
  expect(fetch.mock.calls.filter(([url])=>url.endsWith('/1/overview')).length).toBeGreaterThanOrEqual(2);
  expect(fetch.mock.calls.every(([,options])=>!options?.method || options.method==='GET')).toBe(true);
});

it('does not restore another account’s saved manuscript', async () => {
  sessionStorage.setItem('gsub-eic-workspace-v1',JSON.stringify({userId:999,manuscriptId:1,stage:'Publication'}));
  vi.stubGlobal('fetch',vi.fn(async url => url.endsWith('/manuscripts/') ? {ok:true,json:async()=>[]} : {ok:true,json:async()=>[]}));
  render(<EICDashboard user={{user_id:123,name:'Synthetic'}} token="synthetic" />);
  await screen.findByText('No accessible manuscripts are available.');
  expect(fetch.mock.calls.some(([url])=>url.endsWith('/1/overview'))).toBe(false);
});
it('does not restore manuscript content when the new authorized read is denied', async () => {
  sessionStorage.setItem('gsub-eic-workspace-v1',JSON.stringify({userId:123,manuscriptId:1,stage:'Publication'}));
  vi.stubGlobal('fetch',vi.fn(async url => url.endsWith('/1/overview')
    ? {ok:false,status:403,json:async()=>({detail:'Forbidden'})}
    : {ok:true,json:async()=>[]}));
  render(<EICDashboard user={{user_id:123,name:'Synthetic'}} token="synthetic" />);
  expect((await screen.findByRole('alert')).textContent).toContain('Forbidden');
  expect(screen.queryByText('Abstract 1')).toBeNull();
  expect(screen.queryByRole('navigation',{name:'Manuscript stages'})).toBeNull();
});
it('browses stages through the same dirty guard without writing', async () => {
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'submitted'}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>overview(1)};
    return {ok:false,json:async()=>({})};
  }));
  vi.stubGlobal('confirm',vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  const nav=await screen.findByRole('navigation',{name:'Manuscript stages'});
  await waitFor(()=>expect(within(nav).getByRole('button',{name:/Initial Screening/}).getAttribute('aria-current')).toBe('step'));
  fireEvent.change(screen.getByRole('combobox',{name:'Decision'}),{target:{value:'pass'}});
  fireEvent.click(within(nav).getByRole('button',{name:/Submission/}));
  expect(within(nav).getByRole('button',{name:/Initial Screening/}).getAttribute('aria-pressed')).toBe('true');
  expect(screen.getByRole('combobox',{name:'Decision'}).value).toBe('pass');
  fireEvent.click(within(nav).getByRole('button',{name:/Submission/}));
  expect(within(nav).getByRole('button',{name:/Submission/}).getAttribute('aria-pressed')).toBe('true');
  expect(screen.queryByRole('button',{name:'Previous stage'})).toBeNull();
  fireEvent.click(within(nav).getByRole('button',{name:/Initial Screening/}));
  expect(within(nav).getByRole('button',{name:/Initial Screening/}).getAttribute('aria-pressed')).toBe('true');
  expect(screen.getByRole('combobox',{name:'Decision'}).value).toBe('');
  fireEvent.click(within(nav).getByRole('button',{name:/Publication/}));
  expect(screen.queryByRole('button',{name:'Next stage'})).toBeNull();
  expect(fetch.mock.calls.every(([,options])=>!options?.method || options.method==='GET')).toBe(true);
});
it('opens the current stage, browses nine stages without writes, and guards unsaved input', async () => {
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'submitted'}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>overview(1)};
    return {ok:false,json:async()=>({})};
  }));
  vi.stubGlobal('confirm',vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  const nav=await screen.findByRole('navigation',{name:'Manuscript stages'});
  await waitFor(()=>expect(within(nav).getByRole('button',{name:/Initial Screening/}).getAttribute('aria-current')).toBe('step'));
  expect(within(nav).getAllByRole('button')).toHaveLength(9);
  fireEvent.change(screen.getByRole('combobox',{name:'Decision'}),{target:{value:'pass'}});
  const dirtyUnload = new Event('beforeunload', {cancelable:true});
  window.dispatchEvent(dirtyUnload);
  expect(dirtyUnload.defaultPrevented).toBe(true);
  fireEvent.click(within(nav).getByRole('button',{name:/Publication/}));
  expect(within(nav).getByRole('button',{name:/Initial Screening/}).getAttribute('aria-pressed')).toBe('true');
  expect(screen.getByRole('combobox',{name:'Decision'}).value).toBe('pass');
  fireEvent.click(within(nav).getByRole('button',{name:/Publication/}));
  expect(within(nav).getByRole('button',{name:/Publication/}).getAttribute('aria-pressed')).toBe('true');
  expect(screen.getByText('Publication record is unavailable.')).toBeTruthy();
  fireEvent.click(within(nav).getByRole('button',{name:/Initial Screening/}));
  expect(screen.getByRole('combobox',{name:'Decision'}).value).toBe('');
  const cleanUnload = new Event('beforeunload', {cancelable:true});
  window.dispatchEvent(cleanUnload);
  expect(cleanUnload.defaultPrevented).toBe(false);
  expect(fetch.mock.calls.every(([,options])=>!options?.method || options.method==='GET')).toBe(true);
});

it('keeps a pending or rejected stage save on the same stage with input intact', async () => {
  let finishSave;
  vi.stubGlobal('confirm',vi.fn(()=>true));
  vi.stubGlobal('fetch',vi.fn((url, options={}) => {
    if(options.method === 'POST') return new Promise(resolve => { finishSave=resolve; });
    if(url.endsWith('/manuscripts/')) return Promise.resolve({ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'submitted'}]});
    if(url.endsWith('/eic/editors')) return Promise.resolve({ok:true,json:async()=>[]});
    if(url.endsWith('/1/overview')) return Promise.resolve({ok:true,json:async()=>overview(1)});
    return Promise.resolve({ok:false,json:async()=>({})});
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  const nav=await screen.findByRole('navigation',{name:'Manuscript stages'});
  fireEvent.change(await screen.findByRole('combobox',{name:'Decision'}),{target:{value:'pass'}});
  fireEvent.change(screen.getByRole('textbox',{name:'Comments'}),{target:{value:'Unsaved synthetic comment'}});
  fireEvent.submit(screen.getByRole('button',{name:'Record screening'}).closest('form'));
  await waitFor(()=>expect(finishSave).toBeTypeOf('function'));
  fireEvent.click(within(nav).getByRole('button',{name:/Publication/}));
  expect(within(nav).getByRole('button',{name:/Initial Screening/}).getAttribute('aria-pressed')).toBe('true');
  expect(window.confirm).not.toHaveBeenCalled();
  await act(async()=>finishSave({ok:false,status:400,json:async()=>({detail:'Synthetic rejection'})}));
  expect(await screen.findByText('Action request rejected: Synthetic rejection')).toBeTruthy();
  expect(screen.getByRole('textbox',{name:'Comments'}).value).toBe('Unsaved synthetic comment');
});
it('does not use delayed formatting guidance from a previous manuscript', async () => {
  let finishFirst;
  const detail = id => ({...overview(id), manuscript:{...overview(id).manuscript,manuscript_id:id,status:'formatting'}});
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[1,2].map(id=>({manuscript_id:id,title:`Paper ${id}`,status:'formatting'}))};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>detail(1)};
    if(url.endsWith('/2/overview')) return {ok:true,json:async()=>detail(2)};
    if(url.endsWith('/formatting/manuscripts/1')) return new Promise(resolve => { finishFirst=resolve; });
    if(url.endsWith('/formatting/manuscripts/2')) return {ok:true,json:async()=>({manuscript_id:2,status:'formatting',invitations:[{status:'pending'}],submissions:[]})};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  await waitFor(()=>expect(finishFirst).toBeTypeOf('function'));
  fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
  fireEvent.click(await screen.findByRole('button',{name:/#2 Paper 2/}));
  expect(await screen.findByText('Waiting for the formatter to respond to the invitation.')).toBeTruthy();
  await act(async()=>finishFirst({ok:true,json:async()=>({manuscript_id:1,status:'formatting',invitations:[],submissions:[{status:'pending_eic'}]})}));
  expect(screen.queryByText('The formatted document is awaiting EIC review.')).toBeNull();
  expect(screen.getByText('Waiting for the formatter to respond to the invitation.')).toBeTruthy();
});
it('uses a manuscript ID heading when the selected title is blank', async () => {
  const data = overview(1);
  data.manuscript.title = '  ';
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'submitted'}]};
    if (url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if (url.endsWith('/1/overview')) return {ok:true,json:async()=>data};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button', {name:/#1 Paper 1/}));
  expect(await screen.findByRole('heading', {name:'Manuscript #1'})).toBeTruthy();
});
it('ignores late details when navigating between manuscripts', async () => {
  let resolveFirst;
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[1,2].map(id=>({manuscript_id:id,title:`Paper ${id}`,status:'submitted'}))};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return new Promise(resolve => { resolveFirst=resolve; });
    if(url.endsWith('/2/overview')) return {ok:true,json:async()=>overview(2)};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
  fireEvent.click(await screen.findByRole('button',{name:/#2 Paper 2/}));
  expect(await screen.findByText('Timeline #2')).toBeTruthy();
  resolveFirst({ok:true,json:async()=>overview(1)});
  await waitFor(()=>expect(screen.queryByText('Timeline #1')).toBeNull());
  expect(screen.getByText('Abstract 2')).toBeTruthy();
  expect(screen.getByText('Abstract 2').closest('[data-workspace=selected]')).toBeTruthy();
  const summary = screen.getByText('Activity History');
  expect(summary.parentElement.open).toBe(false);
  fireEvent.click(summary);
  expect(summary.parentElement.open).toBe(true);
  expect(screen.getByText('No activity records are available.')).toBeTruthy();
  const comments = screen.getByText('Workflow Comments').closest('details');
  fireEvent.click(within(comments).getByText('Workflow Comments'));
  expect(within(comments).getByText('No workflow comments are available.')).toBeTruthy();
  expect(screen.queryByRole('button',{name:/refresh/i})).toBeNull();
});

it('shows publication state rather than a reviewer-assignment prompt after publication', async () => {
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'published'}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>({...overview(1),manuscript:{...overview(1).manuscript,status:'published'}})};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  expect(await screen.findByText('Publication recorded in the local prototype.')).toBeTruthy();
  expect(screen.queryByText(/Reviewer assignment is performed/)).toBeNull();
});

it('distinguishes completed assignments from recommendation eligibility and decision progress', async () => {
  const base = overview(1);
  const data = {...base,
    manuscript: {...base.manuscript, status:'ready_for_peer_review'},
    assignments: [
      {assignment_id:1, review_round:1, status:'completed', reviewer:'Synthetic', invitation_status:'legacy', review:{comments:'Synthetic', recommendation:'accept'}},
      {assignment_id:2, review_round:1, status:'assigned', reviewer:'Second', invitation_status:'pending', review:null},
    ],
    review_progress: {can_decide:false, completed_distinct:1, required:1, policy:'legacy', blocked_reason:'All other non-declined invitations and reviews must be completed before a decision.'},
    split_review: {review_round:1, eligible_completed:0, recommendations:[], classification:'insufficient', additional_assignments:[]},
  };
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'ready_for_peer_review'}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>data};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  expect(await screen.findByText('Completed assignment records in this round: 1.')).toBeTruthy();
  const card = (await screen.findByText('Peer Review Progress')).closest('section');
  expect(within(card).getByText('Completed distinct reviewers').previousElementSibling.textContent.replace(/\s/g,'')).toBe('1/1');
  expect(screen.getByText(/0 eligible completed reviews/)).toBeTruthy();
  expect(screen.getByText(/decision-policy count may differ/)).toBeTruthy();
  expect(screen.getByText(/Completed assignments do not automatically qualify/)).toBeTruthy();
  expect(screen.getByText(/Completed assignments do not automatically qualify/).textContent).toContain("Recommendation eligibility requires a completed current-round assignment, an accepted invitation, a reviewer account, a matching round file, and a submitted review with a valid recommendation. Invalidated assignments are excluded. If a reviewer has more than one qualifying review in the round, none of that reviewer's qualifying reviews are counted here.");
  expect(within(card).getByText(/Decision blocked: All other non-declined invitations/)).toBeTruthy();
  fireEvent.click(within(screen.getByRole('navigation',{name:'Manuscript stages'})).getByRole('button',{name:/EIC Decision/}));
  expect(screen.queryByRole('button', {name:'Record editorial decision'})).toBeNull();
});

it('shows all policy-eligible completions when they exceed the minimum', async () => {
  const base = overview(1);
  const assignments = [1,2,3].map(id => ({assignment_id:id, review_round:1, status:'completed', reviewer:`Reviewer ${id}`, invitation_status:'legacy', review:{comments:'Synthetic',recommendation:'accept'}}));
  const data = {...base, manuscript:{...base.manuscript,status:'ready_for_peer_review'}, assignments,
    review_progress:{can_decide:true,completed_distinct:3,required:1,policy:'legacy'},
    split_review:{review_round:1,eligible_completed:0,recommendations:[],classification:'insufficient',additional_assignments:[]}};
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'ready_for_peer_review'}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>data};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  expect(await screen.findByText('Completed assignment records in this round: 3.')).toBeTruthy();
  const card = (await screen.findByText('Peer Review Progress')).closest('section');
  expect(within(card).getByText('Completed distinct reviewers').previousElementSibling.textContent.replace(/\s/g,'')).toBe('3/1');
  expect(screen.getByText(/0 eligible completed reviews/)).toBeTruthy();
  fireEvent.click(within(screen.getByRole('navigation',{name:'Manuscript stages'})).getByRole('button',{name:/EIC Decision/}));
  expect(screen.getByRole('button', {name:'Record editorial decision'})).toBeTruthy();
});


it('uses the guarded list-return handler and separates comments from history', async () => {
  const data = {...overview(1), scans:[{decision:'pass',comments:'Screening comment'}]};
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[1,2].map(id=>({manuscript_id:id,title:`Paper ${id}`,status:'submitted'}))};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>data};
    return {ok:false,json:async()=>({})};
  }));
  vi.stubGlobal('confirm',vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true));
  let goBack; const register = handler => {goBack=handler; return () => {};};
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" registerManuscriptReturn={register} />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  expect(await screen.findByText('Abstract 1')).toBeTruthy();
  expect(await screen.findByText('Initial screening is pending. Check current stage actions.')).toBeTruthy();
  expect(screen.queryByRole('link',{name:'View current stage actions'})).toBeNull();
  expect(screen.getByText('Workflow Comments').closest('details').textContent).toContain('Screening comment');
  expect(screen.getByText('Activity History').closest('details').textContent).not.toContain('Screening comment');
  const input=screen.getByRole('combobox',{name:/decision/i});
  fireEvent.change(input,{target:{value:'pass'}});
  act(()=>{expect(goBack()).toBe(false);});
  expect(screen.getByText('Abstract 1')).toBeTruthy();
  act(()=>{expect(goBack()).toBe(true);});
  expect(await screen.findByRole('button',{name:/#2 Paper 2/})).toBeTruthy();
});

it('keeps private notes and staff comments separate near the top and preserves drafts', async () => {
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'submitted'}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>overview(1)};
    if(url.includes('/notes') || url.includes('/general-comments')) return {ok:true,status:200,json:async()=>[]};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  const notes=await screen.findByText('Private Notes');
  const comments=screen.getByText('Comments (Staff Shared)');
  expect(screen.getAllByText('Private Notes')).toHaveLength(1);
  expect(screen.getAllByText('Comments (Staff Shared)')).toHaveLength(1);
  const stageHeading = await within(document.querySelector('.eic-workflow')).findByRole('heading',{name:'Initial screening',level:3});
  expect(comments.compareDocumentPosition(stageHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(notes);
  fireEvent.change(within(notes.closest('details')).getByLabelText('New note'),{target:{value:'Private draft'}});
  fireEvent.click(notes); fireEvent.click(notes);
  expect(within(notes.closest('details')).getByLabelText('New note').value).toBe('Private draft');
  fireEvent.click(comments);
  fireEvent.change(within(comments.closest('details')).getByLabelText('Add a general comment'),{target:{value:'Staff draft'}});
  fireEvent.click(comments); fireEvent.click(comments);
  expect(within(comments.closest('details')).getByLabelText('Add a general comment').value).toBe('Staff draft');
  expect(screen.getByRole('button',{name:'Record screening'})).toBeTruthy();
});

it('rejects an overview for a different manuscript', async () => {
  vi.stubGlobal('fetch',vi.fn(async url=>{
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'submitted'}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>overview(2)};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  expect(await screen.findByText('Invalid manuscript response.')).toBeTruthy();
  expect(screen.queryByText('Abstract 2')).toBeNull();
});

it('does not restore an old-session overview after the token changes', async () => {
  let finishOld;
  vi.stubGlobal('fetch',vi.fn((url,options={})=>{
    if(url.endsWith('/manuscripts/')) return Promise.resolve({ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'submitted'}]});
    if(url.endsWith('/eic/editors')) return Promise.resolve({ok:true,json:async()=>[]});
    if(url.endsWith('/1/overview') && options.headers.Authorization === 'Bearer old') return new Promise(resolve=>{finishOld=resolve;});
    return Promise.resolve({ok:false,json:async()=>({})});
  }));
  const {rerender}=render(<EICDashboard user={{name:'Synthetic'}} token="old" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  await waitFor(()=>expect(finishOld).toBeTypeOf('function'));
  rerender(<EICDashboard user={{name:'Synthetic'}} token="new" />);
  await act(async()=>finishOld({ok:true,json:async()=>overview(1)}));
  expect(screen.queryByText('Abstract 1')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
  expect(await screen.findByRole('button',{name:/#1 Paper 1/})).toBeTruthy();
});

it('preserves an unsaved EIC choice while refreshing after token rotation', async () => {
  vi.stubGlobal('fetch',vi.fn(async url=>{
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'submitted'}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>overview(1)};
    return {ok:false,json:async()=>({})};
  }));
  const {rerender}=render(<EICDashboard user={{name:'Synthetic'}} token="old" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  const decision=await screen.findByRole('combobox',{name:'Decision'});
  fireEvent.change(decision,{target:{value:'pass'}});
  rerender(<EICDashboard user={{name:'Synthetic'}} token="new" />);
  await waitFor(()=>expect(screen.getByRole('combobox',{name:'Decision'}).value).toBe('pass'));
});

it('requires a valid current round even when server decision flag is true', async () => {
  const data={...overview(1),manuscript:{...overview(1).manuscript,status:'ready_for_peer_review',review_round:null},review_progress:{can_decide:true}};
  vi.stubGlobal('fetch',vi.fn(async url=>{
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'ready_for_peer_review'}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>data};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  expect(await screen.findByText('Review-round information is unavailable or inconsistent. Refresh before acting.')).toBeTruthy();
  expect(screen.queryByRole('button',{name:'View editorial decision'})).toBeNull();
  fireEvent.click(within(screen.getByRole('navigation',{name:'Manuscript stages'})).getByRole('button',{name:/EIC Decision/}));
  expect(screen.queryByRole('button',{name:'Record editorial decision'})).toBeNull();
});

it('offers the existing decision view only when the server confirms eligibility', async () => {
  const data={...overview(1),manuscript:{...overview(1).manuscript,status:'ready_for_peer_review'},review_progress:{can_decide:true}};
  vi.stubGlobal('fetch',vi.fn(async url=>{
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'ready_for_peer_review'}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>data};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  fireEvent.click(await screen.findByRole('button',{name:'View editorial decision'}));
  expect(screen.getByRole('button',{name:'Record editorial decision'})).toBeTruthy();
  expect(fetch.mock.calls.every(([,options])=>!options?.method || options.method==='GET')).toBe(true);
});

it('follows a newly current stage after a confirmed screening action', async () => {
  let status='submitted';
  vi.stubGlobal('fetch',vi.fn(async (url,options={})=>{
    if(url.endsWith('/initial-scan') && options.method==='POST') {status='initial_scan_passed';return {ok:true,status:201,json:async()=>({})};}
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status}]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>({...overview(1),manuscript:{...overview(1).manuscript,status}})};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  fireEvent.change(await screen.findByRole('combobox',{name:'Decision'}),{target:{value:'pass'}});
  fireEvent.change(screen.getByRole('textbox',{name:'Comments'}),{target:{value:'Synthetic screening'}});
  fireEvent.click(screen.getByRole('button',{name:'Record screening'}));
  await waitFor(()=>expect(within(screen.getByRole('navigation',{name:'Manuscript stages'})).getByRole('button',{name:/Initial Editing/}).getAttribute('aria-pressed')).toBe('true'));
  expect(screen.getByRole('heading',{name:'Initial Editor Assignment'})).toBeTruthy();
});

it.each(['Submission','Initial Screening','Initial Editing','Peer Review','EIC Decision','Author Agreement','Final Editing','Formatting','Publication'])('opens the %s workspace and returns to manuscript progress', async stage => {
  const scroll = vi.fn();
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scroll });
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[{manuscript_id:1,title:'Paper 1',status:'submitted'}]};
    if (url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if (url.endsWith('/1/overview')) return {ok:true,json:async()=>overview(1)};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Paper 1/}));
  const navigation=await screen.findByRole('navigation',{name:'Manuscript stages'});
  fireEvent.click(within(navigation).getByRole('button',{name:`View ${stage} workspace`}));
  const workspace=document.getElementById('eic-current-actions');
  await waitFor(()=>expect(workspace.querySelector('[data-eic-stage]')?.getAttribute('data-eic-stage')).toBe(stage));
  await waitFor(()=>expect(document.activeElement).toBe(workspace));
  expect(scroll).toHaveBeenCalled();
  expect(within(workspace).queryByRole('button',{name:'Back to Manuscript Progress'})).toBeNull();
  fireEvent.click(within(navigation).getByRole('button',{name:'View Submission workspace'}));
  await waitFor(()=>expect(workspace.querySelector('[data-eic-stage]')?.getAttribute('data-eic-stage')).toBe('Submission'));
  delete HTMLElement.prototype.scrollIntoView;
});
