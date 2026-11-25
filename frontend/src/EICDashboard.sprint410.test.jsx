import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useEffect } from 'react';
import EICDashboard from './EICDashboard';
import { EICDecisionStageView } from './EICStageViews';

const state = vi.hoisted(() => ({ target: '#eic-decision-1', round: 1 }));
vi.mock('./NotificationBell', () => ({ default: () => null }));
vi.mock('./ManuscriptProgress', () => ({ default: ({ manuscriptId, onProgressChange }) => {
  useEffect(() => onProgressChange?.({manuscript_id: manuscriptId, review_round: state.round,
    current_stage:'Peer Review', stages:[], participant_task:{task_state:'action_required',
    task_message:'Review the current editorial decision controls.', relevant_stage:'Peer Review',
    action_label:'View editorial decision', permitted_action_target:state.target}}), [manuscriptId, onProgressChange]);
  return null;
} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });

it.each([['#eic-decision-1',1,true], ['#eic-decision-2',1,false],
  ['https://example.invalid/',1,false], ['#eic-decision-1',2,false]])
('only follows an eligible current manuscript and round destination', async (target, round, allowed) => {
  state.target=target; state.round=round;
  const manuscript={manuscript_id:1,title:'Synthetic',status:'ready_for_peer_review',author:'Synthetic',abstract:'Synthetic',review_round:1};
  const overview={manuscript,review_progress:{can_decide:true},decisions:[],submissions:[],final_invitations:[],final_workflow_submissions:[],scans:[],invitations:[],confirmations:[],assignments:[],author_agreement:null,final_submissions:[]};
  vi.stubGlobal('fetch',vi.fn(async url => {
    if(url.endsWith('/manuscripts/')) return {ok:true,json:async()=>[manuscript]};
    if(url.endsWith('/eic/editors')) return {ok:true,json:async()=>[]};
    if(url.endsWith('/1/overview')) return {ok:true,json:async()=>overview};
    return {ok:false,json:async()=>({})};
  }));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Synthetic/}));
  await screen.findByText(round === 2 ? 'Review-round information is unavailable or inconsistent. Refresh before acting.' : 'Review the current editorial decision controls.');
  if (allowed) {
    const link=await screen.findByRole('link',{name:'View editorial decision'});
    expect(link.getAttribute('href')).toBe('#eic-decision-1');
    fireEvent.click(link);
    expect(await screen.findByRole('button',{name:'Record editorial decision'})).toBeTruthy();
    expect(document.querySelector('#eic-decision-1')).toBeTruthy();
  } else expect(screen.queryByRole('link',{name:'View editorial decision'})).toBeNull();
});

it('submits the displayed manuscript and review round with the decision', () => {
  const act=vi.fn();
  render(<EICDecisionStageView selected={12} round={3} decision="reject" comments="Synthetic"
    setDecision={vi.fn()} setComments={vi.fn()} act={act} busy={false} needsRefresh={false} />);
  fireEvent.click(screen.getByRole('button',{name:'Record editorial decision'}));
  expect(act).toHaveBeenCalledWith('/eic/manuscripts/12/decision',
    {decision:'reject',comments:'Synthetic',expected_review_round:3});
});
