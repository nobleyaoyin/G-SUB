import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, render, screen} from '@testing-library/react';
import EICStageContent from './EICStageContent';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const overview = {manuscript:{manuscript_id:1, review_round:1}, scans:[], invitations:[], submissions:[], confirmations:[], assignments:[], decisions:[], final_invitations:[], final_workflow_submissions:[], author_agreement:null};
const context = {overview, currentStage:'Peer Review', status:'ready_for_peer_review', approval:[], canDecide:false, download:vi.fn()};
const names = ['Submission','Initial Screening','Initial Editing','Peer Review','EIC Decision','Author Agreement','Final Editing','Formatting','Publication'];

it('selects exactly one independent view for each existing stage without fetching', () => {
  vi.stubGlobal('fetch',vi.fn());
  const view=render(<EICStageContent stage={names[0]} context={context} />);
  for (const stage of names) {
    view.rerender(<EICStageContent stage={stage} context={context} />);
    const stageViews=view.container.querySelectorAll('[data-eic-stage]');
    expect(stageViews).toHaveLength(1);
    expect(stageViews[0].getAttribute('data-eic-stage')).toBe(stage);
    expect(screen.getByRole('region',{name:`${stage} history`})).toBeTruthy();
  }
  view.rerender(<EICStageContent stage="unknown" context={context} />);
  expect(view.container.querySelector('[data-eic-stage]')).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});

it('does not expose screening or decision actions without current eligibility', () => {
  const view=render(<EICStageContent stage="Initial Screening" context={context} />);
  expect(screen.queryByRole('button',{name:'Record screening'})).toBeNull();
  view.rerender(<EICStageContent stage="EIC Decision" context={context} />);
  expect(screen.queryByRole('button',{name:'Record editorial decision'})).toBeNull();
  expect(screen.getByText('A decision action is not currently available.')).toBeTruthy();
});
