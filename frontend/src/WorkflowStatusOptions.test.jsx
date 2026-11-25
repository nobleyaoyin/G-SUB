import {afterEach, expect, it} from 'vitest';
import {cleanup, render, screen} from '@testing-library/react';
import WorkflowStatusOptions from './WorkflowStatusOptions';
import {WORKFLOW_STAGES, matchesWorkflowFilter, statusMainStage} from './workflowStatus';
import {selectRoleItems} from './RoleListControls';
import {selectManuscripts} from './authorManuscriptView';
import {prepareManuscriptList} from './eicManuscriptList';
afterEach(cleanup);
it('maps each recorded status to the ordered stage and refuses to infer proofing', () => {
  expect(WORKFLOW_STAGES.map(([stage]) => stage)).toEqual(['Submission','Initial Screening','Initial Editing','Peer Review','EIC Decision','Author Agreement','Final Editing','Formatting','Proofing','Publication']);
  for (const [stage, statuses] of WORKFLOW_STAGES) for (const status of statuses) {
    expect(statusMainStage(status)).toBe(stage);
    expect(matchesWorkflowFilter({status}, `stage:${stage}`)).toBe(true);
  }
  expect(statusMainStage('formatting')).toBeNull();
  expect(matchesWorkflowFilter({status:'formatting'},'stage:Proofing')).toBe(false);
  expect(matchesWorkflowFilter({status:'assigned'},'stage:Peer Review')).toBe(false);
});
it('shows recorded statuses and permits evidence-backed proof stage selection', () => {
  render(<select aria-label="Status"><WorkflowStatusOptions items={[{status:'draft'},{status:'formatting'}]}/></select>);
  expect(screen.getByRole('option',{name:'Proofing'}).disabled).toBe(false);
  expect(matchesWorkflowFilter({status:'formatting',workflow_stage:'Proofing'},'stage:Proofing')).toBe(true);
  expect(matchesWorkflowFilter({status:'formatting',workflow_stage:null},'stage:Proofing')).toBe(false);
  expect(screen.getByRole('option',{name:'Formatting / proofing — stage unavailable'}).value).toBe('formatting');
  expect(screen.queryByRole('option',{name:'revised'})).toBeNull();
});
it('filters role, author and EIC lists without introducing records', () => {
  const items=[{manuscript_id:1,title:'One',status:'draft'},{manuscript_id:2,title:'Two',status:'published'}];
  const filter='stage:Submission';
  expect(selectRoleItems(items,'',filter,'recent').map(x=>x.manuscript_id)).toEqual([1]);
  expect(selectManuscripts(items,'',filter,'recent').map(x=>x.manuscript_id)).toEqual([1]);
  expect(prepareManuscriptList(items,'',filter,'id','asc').filtered.map(x=>x.manuscript_id)).toEqual([1]);
});
