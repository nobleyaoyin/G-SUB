import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import ReviewerDashboard from './ReviewerDashboard';

vi.mock('./NotificationBell', () => ({ default: () => null }));
vi.mock('./ReviewerProfilePanel', () => ({ default: () => null }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const headers = new Headers({ 'content-type': 'application/json' });
const response = value => ({ ok: true, headers, json: async () => value });
const assignment = id => ({ assignment_id:id, manuscript_id:id, review_round:1, status:'assigned', invitation_status:'pending' });
const task = (state, message) => ({ task_state:state, task_message:message, relevant_stage:'Peer Review', action_label:null, permitted_action_target:null });

it('shows the owner-scoped pending task without offering a document', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => response(url.endsWith('/assignments/my') ? [assignment(1)] : task('pending','Your review invitation is awaiting a response.'))));
  render(<ReviewerDashboard user={{user_id:1,name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
  expect(await screen.findByText(/Your review invitation is awaiting a response/)).toBeTruthy();
  expect(screen.queryByRole('button',{name:'Download Review File'})).toBeNull();
});

it('discards a late task after switching assignments', async () => {
  let finishFirst;
  vi.stubGlobal('fetch', vi.fn(url => {
    if (url.endsWith('/assignments/my')) return Promise.resolve(response([assignment(1), assignment(2)]));
    if (url.endsWith('/assignments/1/task')) return new Promise(resolve => { finishFirst = resolve; });
    return Promise.resolve(response(task('declined','You declined this review invitation.')));
  }));
  render(<ReviewerDashboard user={{user_id:1,name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByRole('heading',{name:'Manuscript #1'})).closest('.reviewer-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
  fireEvent.click(within(screen.getByRole('heading',{name:'Manuscript #2'}).closest('.reviewer-card')).getByRole('button',{name:'Open manuscript'}));
  expect(await screen.findByText(/You declined this review invitation/)).toBeTruthy();
  await act(async () => finishFirst(response(task('pending','STALE FIRST TASK'))));
  expect(screen.queryByText(/STALE FIRST TASK/)).toBeNull();
});

it('links only an eligible assignment task to its own review form', async () => {
  const eligible = {...assignment(1), invitation_status:'accepted', review_file_available:true};
  vi.stubGlobal('fetch', vi.fn(async url => response(url.endsWith('/assignments/my') ? [eligible]
    : url.endsWith('/assignments/1/task') ? {...task('action_required','Submit your review.'),
      action_label:'View review form', permitted_action_target:'#review-action-1'}
    : url.endsWith('/progress') ? {manuscript_id:1,current_stage:'Peer Review',stages:[]}
    : [])));
  render(<ReviewerDashboard user={{user_id:1,name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
  expect((await screen.findByRole('link',{name:'View review form'})).getAttribute('href')).toBe('#review-action-1');
  expect(screen.getByRole('heading',{name:'Submit Review'}).closest('#review-action-1')).toBeTruthy();
});
