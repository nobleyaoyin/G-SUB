import {useState} from 'react';
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import StageFilterControls from './StageFilterControls';
import {matchesWorkflowFilter} from './workflowStatus';
afterEach(cleanup);
it('selects, changes and clears stages and recorded sub-stages independently', () => {
  const items=[{status:'revised'},{status:'revision_required'},{status:'draft'}];
  function Fixture(){const [value,setValue]=useState('');return <><StageFilterControls value={value} onChange={setValue} items={items} onClear={()=>setValue('')}/><output>{value}</output></>}
  render(<Fixture/>);
  expect(screen.getByLabelText('Sub-stage').disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Main stage'),{target:{value:'Peer Review'}});
  expect(screen.getByRole('option',{name:'Revised'})).toBeTruthy();
  expect(screen.queryByRole('option',{name:'Draft'})).toBeNull();
  fireEvent.change(screen.getByLabelText('Sub-stage'),{target:{value:'revised'}});
  expect(screen.getByText('stage:Peer Review|status:revised')).toBeTruthy();
  expect(matchesWorkflowFilter(items[0],'stage:Peer Review|status:revised')).toBe(true);
  expect(matchesWorkflowFilter(items[1],'stage:Peer Review|status:revised')).toBe(false);
  fireEvent.change(screen.getByLabelText('Sub-stage'),{target:{value:''}});
  expect(screen.getByText('stage:Peer Review')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Clear filters'}));
  expect(screen.getByLabelText('Sub-stage').disabled).toBe(true);
});
it('does not fabricate proof review statuses',()=>{
  render(<StageFilterControls value="stage:Proofing" onChange={vi.fn()} items={[{status:'formatting',workflow_stage:'Proofing'}]}/>);
  expect(screen.getByText(/proof review sub-stages are unavailable/i)).toBeTruthy();
  expect(screen.getByLabelText('Sub-stage').options).toHaveLength(1);
});
it('filters only substages supplied by the authorized projection',()=>{
  const onChange=vi.fn();
  const items=[{status:'formatting',workflow_stage:'Proofing',workflow_substage:'pending_author'},
    {status:'formatting',workflow_stage:'Proofing',workflow_substage:null}];
  render(<StageFilterControls value="stage:Proofing" onChange={onChange} items={items}/>);
  expect(screen.getByText(/some proof review sub-stages are unavailable/i)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Sub-stage'),{target:{value:'proof:pending_author'}});
  expect(onChange).toHaveBeenCalledWith('stage:Proofing|status:proof:pending_author');
  expect(matchesWorkflowFilter(items[0],'stage:Proofing|status:proof:pending_author')).toBe(true);
  expect(matchesWorkflowFilter(items[1],'stage:Proofing|status:proof:pending_author')).toBe(false);
});

it('never matches one verified current stage to both Formatting and Proofing',()=>{
  const item={status:'formatting',workflow_stage:'Proofing',workflow_substage:'pending_author'};
  expect(matchesWorkflowFilter(item,'stage:Proofing')).toBe(true);
  expect(matchesWorkflowFilter(item,'stage:Formatting')).toBe(false);
  expect(matchesWorkflowFilter(item,'stage:Proofing|status:proof:pending_author')).toBe(true);
});

it('offers a recorded declined Formatter invitation without inventing a Proofing state',()=>{
  render(<StageFilterControls value="stage:Formatting" onChange={vi.fn()} items={[{status:'formatting',workflow_stage:'Formatting',workflow_substage:'formatter_declined'}]}/>);
  expect(screen.getByRole('option',{name:'Formatter invitation declined'}).value).toBe('proof:formatter_declined');
  expect(matchesWorkflowFilter({status:'formatting',workflow_stage:'Formatting',workflow_substage:'formatter_declined'},'stage:Proofing')).toBe(false);
});
