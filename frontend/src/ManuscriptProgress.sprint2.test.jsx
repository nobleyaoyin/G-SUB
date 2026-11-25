import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import ManuscriptProgress from './ManuscriptProgress';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('opens a stage description directly without a duplicate selector', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok: true, json: async () => ({
    manuscript_id: 1, current_stage: 'Initial Screening', review_round: 1,
    stages: [{name:'Submission',state:'completed'}, {name:'Initial Screening',state:'current'}, {name:'Peer Review',state:'pending'}],
  })})));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  const stage = await screen.findByText('Submission');
  expect(screen.queryByRole('combobox', {name:'Browse workflow milestones'})).toBeNull();
  fireEvent.click(stage.closest('summary'));
  expect(screen.getByText('This stage covers manuscript preparation and submission.').closest('details').open).toBe(true);
  expect(screen.getByText('Upcoming')).toBeTruthy();
});

it('refreshes progress for a different manuscript', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => ({ok:true, json:async()=>({
    manuscript_id: url.includes('/2/') ? 2 : 1, current_stage:'Submission', review_round:1,
    stages:[{name:'Submission',state:'current'}],
  })})));
  const view = render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  expect(await screen.findByText('Manuscript (#1)')).toBeTruthy();
  view.rerender(<ManuscriptProgress manuscriptId={2} token="synthetic" />);
  expect(await screen.findByText('Manuscript (#2)')).toBeTruthy();
  expect(screen.queryByText('Manuscript (#1)')).toBeNull();
});

it('links only an authorized matching initial-editing task to its local workspace', async () => {
  let task = {task_state:'action_required', task_message:'Review the submitted initial edit.',
    relevant_stage:'Initial Editing', action_label:'View initial editing', permitted_action_target:'#initial-editing-action-1'};
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:1,
    current_stage:'Initial Editing', stages:[], participant_task:task})})));
  const view = render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  expect((await screen.findByRole('link', {name:'View initial editing'})).getAttribute('href')).toBe('#initial-editing-action-1');
  task = {...task, permitted_action_target:'https://example.invalid/'};
  view.rerender(<ManuscriptProgress manuscriptId={1} token="synthetic" revision={1} />);
  await screen.findByText(/Review the submitted initial edit/);
  await vi.waitFor(() => expect(screen.queryByRole('link', {name:'View initial editing'})).toBeNull());
});

it.each([
  ['Author Agreement', 'View author agreement', '#author-agreement-action-1'],
  ['Final Editing', 'View final editing', '#final-editing-action-1'],
])('links a verified %s task to the matching local workspace', async (stage, label, target) => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:1,
    current_stage:stage, stages:[], participant_task:{task_state:'action_required',task_message:'Review the next action.',
      relevant_stage:stage, action_label:label, permitted_action_target:target}})})));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  expect((await screen.findByRole('link', {name:label})).getAttribute('href')).toBe(target);
});

it.each(['Submission', 'Initial Screening', 'Peer Review'])('links the author to manuscript actions in %s', async stage => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:1,
    current_stage:stage, stages:[], participant_task:{task_state:'action_required',task_message:'Prepare your manuscript.',
      relevant_stage:stage, action_label:'View manuscript actions', permitted_action_target:'#author-manuscript-actions-1'}})})));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  expect((await screen.findByRole('link', {name:'View manuscript actions'})).getAttribute('href')).toBe('#author-manuscript-actions-1');
});
