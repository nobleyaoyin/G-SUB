import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import ManuscriptProgress from './ManuscriptProgress';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('uses one validated current-stage participant task instead of generic guidance', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:1,review_round:1,current_stage:'Peer Review',next_action:'Generic message',stages:[],participant_task:{task_state:'waiting',task_message:'Waiting for editorial action.',relevant_stage:'Peer Review',action_label:null,permitted_action_target:null}})})));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  expect(await screen.findByText(/Waiting for editorial action/)).toBeTruthy();
  expect(screen.getByText('(Waiting)')).toBeTruthy();
  expect(screen.queryByText('Generic message')).toBeNull();
  expect(screen.queryByRole('link')).toBeNull();
});

it('does not display a task for another stage', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:1,review_round:1,current_stage:'Peer Review',next_action:'Current guidance',stages:[],participant_task:{task_state:'action_required',task_message:'Old stage task',relevant_stage:'Formatting'}})})));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  expect(await screen.findByText(/Current task information is unavailable/)).toBeTruthy();
  expect(screen.queryByText('Old stage task')).toBeNull();
});

it('uses the author compatibility message only when the server has no task projection', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:1,review_round:1,current_stage:'Submission',next_action:'Generic',stages:[]})})));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" fallbackAction="Complete the draft." />);
  expect(await screen.findByText(/Complete the draft/)).toBeTruthy();
  expect(screen.queryByText('Generic')).toBeNull();
});

it('omits the temporary refresh helper without exposing disabled task actions', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:1,current_stage:'Submission',stages:[],participant_task:{task_state:'action_required',task_message:'Complete the draft.',relevant_stage:'Submission',action_label:'View manuscript actions',permitted_action_target:'#author-manuscript-actions-1'}})})));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" taskDisabled />);
  await screen.findByText('No workflow stages are listed in this view.');
  expect(screen.queryByText(/Current task information is unavailable while progress is refreshed/)).toBeNull();
  expect(screen.queryByRole('link',{name:'View manuscript actions'})).toBeNull();
});
