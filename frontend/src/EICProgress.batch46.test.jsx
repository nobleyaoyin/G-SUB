import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EICDashboard from './EICDashboard';

vi.mock('./NotificationBell', () => ({default: () => null}));
vi.mock('./FormattingPanel', () => ({default: () => null}));
vi.mock('./BlindReviewPanel', () => ({default: () => null}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function browseStage(name) {
  const timeline=screen.getByRole('list',{name:'Workflow timeline'});
  const details=within(timeline).getByText(name,{exact:true}).closest('details');
  if (!details.open) fireEvent.click(within(details).getByText(name,{exact:true}));
  fireEvent.click(within(details).getByRole('button',{name:`View ${name} workspace`}));
}

it('keeps timeline browsing and actions available with one review round', async () => {
  const overview = {manuscript:{manuscript_id:1,title:'Synthetic paper',status:'submitted',author:'Synthetic',abstract:'Synthetic',review_round:null},
    review_progress:{can_decide:false},decisions:[],submissions:[],final_invitations:[],final_workflow_submissions:[],
    scans:[],invitations:[],confirmations:[],assignments:[],author_agreement:null,final_submissions:[]};
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>
    url.endsWith('/manuscripts/') ? [{manuscript_id:1,title:'Synthetic paper',status:'submitted'}]
    : url.endsWith('/eic/editors') ? [] : url.endsWith('/overview') ? overview
    : url.endsWith('/progress') ? {manuscript_id:1,review_round:2,current_stage:'Initial Screening',next_action:'Screen',
       stages:[{name:'Initial Screening',state:'current',steps:[{name:'Screen',state:'current'}]}]}
    : []})));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Synthetic paper/}));
  const timeline = await screen.findByRole('list',{name:'Workflow timeline'});
  expect(within(timeline).getByText('Initial screening')).toBeTruthy();
  await waitFor(() => expect(screen.getByText('Review round:').parentElement.textContent).toContain('2'));
  expect(screen.getAllByText('Review round:')).toHaveLength(1);
  expect(screen.getByRole('button',{name:'Record screening'}).closest('details')).toBeNull();
  expect(screen.getByText('Publication is a local prototype.').closest('details')).toBeNull();
  const nextAction = screen.getByText('Next action:').parentElement;
  expect(nextAction.closest('.eic-workflow-heading')).toBeTruthy();
  expect(screen.getAllByText('Next action:')).toHaveLength(1);
  const publication = within(timeline).getByText('Publication').closest('details');
  fireEvent.click(within(publication).getByText('Publication'));
  const action = within(publication).getByRole('button',{name:'View Publication workspace'});
  action.focus(); expect(document.activeElement).toBe(action);
  await userEvent.keyboard('{Enter}');
  expect(nextAction.textContent).toContain('This stage is being viewed for context');
  expect(nextAction.closest('details')).toBeNull();
});

it('does not offer a decision when progress and overview rounds disagree', async () => {
  const overview = {manuscript:{manuscript_id:1,title:'Synthetic paper',status:'revised',author:'Synthetic',abstract:'Synthetic',review_round:2},
    review_progress:{can_decide:true},decisions:[],submissions:[],final_invitations:[],final_workflow_submissions:[],scans:[],invitations:[],confirmations:[],assignments:[],author_agreement:null,final_submissions:[]};
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/manuscripts/') ? [{manuscript_id:1,title:'Synthetic paper',status:'revised'}]
    : url.endsWith('/eic/editors') ? [] : url.endsWith('/overview') ? overview
    : url.endsWith('/progress') ? {manuscript_id:1,review_round:1,current_stage:'Peer Review',stages:[],participant_task:{task_state:'action_required',task_message:'Stale decision task',relevant_stage:'Peer Review'}} : []})));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Synthetic paper/}));
  expect(await screen.findByText('Review-round information is unavailable or inconsistent. Refresh before acting.')).toBeTruthy();
  expect(screen.queryByText('Stale decision task')).toBeNull();
  expect(screen.queryByRole('button',{name:'View editorial decision'})).toBeNull();
  browseStage('EIC decision');
  expect(screen.queryByRole('button',{name:'Record editorial decision'})).toBeNull();
});

it('displays a current-stage projected task without adding a second prompt', async () => {
  const overview = {manuscript:{manuscript_id:1,title:'Synthetic paper',status:'submitted',author:'Synthetic',abstract:'Synthetic',review_round:1},
    review_progress:{can_decide:false},decisions:[],submissions:[],final_invitations:[],final_workflow_submissions:[],scans:[],invitations:[],confirmations:[],assignments:[],author_agreement:null,final_submissions:[]};
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/manuscripts/') ? [{manuscript_id:1,title:'Synthetic paper',status:'submitted'}]
    : url.endsWith('/eic/editors') ? [] : url.endsWith('/overview') ? overview
    : url.endsWith('/progress') ? {manuscript_id:1,review_round:1,current_stage:'Initial Screening',stages:[],participant_task:{task_state:'action_required',task_message:'Review the current screening task.',relevant_stage:'Initial Screening'}} : []})));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Synthetic paper/}));
  expect(await screen.findByText('Review the current screening task.')).toBeTruthy();
  expect(screen.getAllByText('Next action:')).toHaveLength(1);
});

it('associates the decision prompt with the authorized decision stage', async () => {
  const overview = {manuscript:{manuscript_id:1,title:'Synthetic paper',status:'ready_for_peer_review',author:'Synthetic',abstract:'Synthetic',review_round:1},
    review_progress:{can_decide:true},decisions:[],submissions:[],final_invitations:[],final_workflow_submissions:[],scans:[],invitations:[],confirmations:[],assignments:[],author_agreement:null,final_submissions:[]};
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/manuscripts/') ? [{manuscript_id:1,title:'Synthetic paper',status:'ready_for_peer_review'}]
    : url.endsWith('/eic/editors') ? [] : url.endsWith('/overview') ? overview
    : url.endsWith('/progress') ? {manuscript_id:1,review_round:1,current_stage:'Peer Review',stages:[],participant_task:{task_state:'action_required',task_message:'Review the current editorial decision controls.',relevant_stage:'Peer Review'}} : []})));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Synthetic paper/}));
  fireEvent.click(await screen.findByRole('button',{name:'View editorial decision'}));
  expect(screen.getByText('Review the editorial decision controls for the current round.')).toBeTruthy();
  expect(screen.getByRole('button',{name:'Record editorial decision'})).toBeTruthy();
  browseStage('Publication');
  expect(screen.getByText('This stage is being viewed for context; the current workflow task is unchanged.')).toBeTruthy();
  expect(screen.queryByRole('button',{name:'Record editorial decision'})).toBeNull();
});
