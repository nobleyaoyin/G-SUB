import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useEffect } from 'react';
import EICDashboard from './EICDashboard';
const state = vi.hoisted(() => ({ target: '#eic-initial-assignment-1' }));
vi.mock('./NotificationBell', () => ({ default: () => null }));
vi.mock('./ManuscriptProgress', () => ({ default: ({ manuscriptId, onProgressChange }) => {
  useEffect(() => onProgressChange?.({ manuscript_id: manuscriptId, review_round: 1,
    current_stage: 'Initial Editing', stages: [{name:'Initial Editing',state:'current'}],
    participant_task: {task_state:'action_required', task_message:'Invite an initial editor.',
      relevant_stage:'Initial Editing', action_label:'View initial editor assignment',
      permitted_action_target:state.target} }), [manuscriptId,onProgressChange]);
  return null;
} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.removeItem('gsub-eic-workspace-v1'); });
it.each([
  ['#eic-initial-assignment-1', true],
  ['#eic-initial-assignment-2', false],
  ['https://example.invalid/', false],
])('only renders the current manuscript task destination (%s)', async (target, visible) => {
  state.target = target;
  const manuscript={manuscript_id:1,title:'Synthetic',status:'initial_scan_passed',author:'Synthetic',abstract:'Synthetic',review_round:1};
  const overview={manuscript,review_progress:{can_decide:false},decisions:[],submissions:[],final_invitations:[],final_workflow_submissions:[],scans:[],invitations:[],confirmations:[],assignments:[],author_agreement:null,final_submissions:[]};
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[manuscript]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>overview};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Synthetic/}));
  await waitFor(()=>expect(screen.getByRole('heading',{name:'Initial Editor Assignment'})).toBeTruthy());
  const link=screen.queryByRole('link',{name:'View initial editor assignment'});
  if(visible) {
    expect(link?.getAttribute('href')).toBe('#eic-initial-assignment-1');
    expect(document.querySelector(link.getAttribute('href'))).toBeTruthy();
  } else expect(link).toBeNull();
});
