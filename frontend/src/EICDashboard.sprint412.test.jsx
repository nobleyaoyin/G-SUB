import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useEffect } from 'react';
import EICDashboard from './EICDashboard';
const state=vi.hoisted(()=>({target:'#eic-reviewer-management-1',round:1}));
vi.mock('./NotificationBell',()=>({default:()=>null}));
vi.mock('./ManuscriptProgress',()=>({default:({manuscriptId,onProgressChange})=>{
  useEffect(()=>onProgressChange?.({manuscript_id:manuscriptId,review_round:state.round,current_stage:'Peer Review',stages:[],participant_task:{task_state:'action_required',task_message:'Invite a reviewer for the current round.',relevant_stage:'Peer Review',action_label:'View reviewer invitations',permitted_action_target:state.target}}),[manuscriptId,onProgressChange]); return null;
}}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();sessionStorage.clear();});
it.each([['#eic-reviewer-management-1',1,true],['#eic-reviewer-management-2',1,false],['https://example.invalid/',1,false],['#eic-reviewer-management-1',2,false]])('allows only the current manuscript and round target',async(target,round,allowed)=>{
  state.target=target;state.round=round;
  const manuscript={manuscript_id:1,title:'Synthetic',status:'ready_for_peer_review',author:'Synthetic',abstract:'Synthetic',review_round:1};
  const overview={manuscript,review_progress:{can_decide:false,active_assignments:0},decisions:[],submissions:[],final_invitations:[],final_workflow_submissions:[],scans:[],invitations:[],confirmations:[],assignments:[],author_agreement:null,final_submissions:[]};
  vi.stubGlobal('fetch',vi.fn(async url=>{if(url.endsWith('/manuscripts/'))return{ok:true,json:async()=>[manuscript]};if(url.endsWith('/eic/editors'))return{ok:true,json:async()=>[]};if(url.endsWith('/1/overview'))return{ok:true,json:async()=>overview};return{ok:false,json:async()=>({})};}));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic"/>);
  fireEvent.click(await screen.findByRole('button',{name:/#1 Synthetic/}));
  await screen.findByText(round===2?'Review-round information is unavailable or inconsistent. Refresh before acting.':'Invite a reviewer for the current round.');
  if(allowed){const link=await screen.findByRole('link',{name:'View reviewer invitations'});expect(link.getAttribute('href')).toBe('#eic-reviewer-management-1');expect(document.querySelector(link.getAttribute('href'))).toBeTruthy();}
  else expect(screen.queryByRole('link',{name:'View reviewer invitations'})).toBeNull();
});
