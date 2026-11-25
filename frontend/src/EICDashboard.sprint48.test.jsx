import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useEffect } from 'react';
import EICDashboard from './EICDashboard';
const state = vi.hoisted(() => ({ target: '#eic-initial-review-1' }));
vi.mock('./NotificationBell', () => ({ default: () => null }));
vi.mock('./ManuscriptProgress', () => ({ default: ({ manuscriptId, onProgressChange }) => {
  useEffect(() => onProgressChange?.({ manuscript_id: manuscriptId, review_round: 1,
    current_stage: 'Initial Editing', stages: [{name:'Initial Editing',state:'current'}],
    participant_task: {task_state:'action_required', task_message:'Review the editor-approved initial edit.',
      relevant_stage:'Initial Editing', action_label:'View initial editing review',
      permitted_action_target:state.target} }), [manuscriptId,onProgressChange]);
  return null;
} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.removeItem('gsub-eic-workspace-v1'); });
it.each([
  ['#eic-initial-review-1', true],
  ['#eic-initial-review-2', false],
  ['https://example.invalid/', false],
])('only renders the current manuscript task destination (%s)', async (target, visible) => {
  state.target = target;
  const manuscript={manuscript_id:1,title:'Synthetic',status:'initial_editing',author:'Synthetic',abstract:'Synthetic',review_round:1};
  const overview={manuscript,review_progress:{can_decide:false},decisions:[],submissions:[{submission_id:5,status:'editor_approved',editor:'Synthetic'}],final_invitations:[],final_workflow_submissions:[{submission_id:5,status:'editor_approved',editor:'Synthetic'}],scans:[],invitations:[],confirmations:[],assignments:[],author_agreement:null,final_submissions:[{submission_id:5,status:'editor_approved',editor:'Synthetic'}]};
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[manuscript]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>overview};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Synthetic/}));
  await waitFor(()=>expect(screen.getByRole('heading',{name:'Initial Editing Review'})).toBeTruthy());
  const link=screen.queryByRole('link',{name:'View initial editing review'});
  if(visible) {
    expect(link?.getAttribute('href')).toBe('#eic-initial-review-1');
    expect(document.querySelector(link.getAttribute('href'))).toBeTruthy();
  } else expect(link).toBeNull();
});
