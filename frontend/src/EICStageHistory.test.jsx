import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import EICStageHistory from './EICStageHistory';

afterEach(cleanup);
const base = {manuscript:{manuscript_id:1,status:'published',review_round:2},invitations:[],submissions:[],confirmations:[],scans:[],decisions:[],assignments:[],final_invitations:[],final_workflow_submissions:[],author_agreement:null};

it('separates review rounds without exposing identities or review comments', () => {
  const overview={...base,assignments:[
    {assignment_id:1,review_round:1,reviewer:'Private reviewer',status:'completed',invitation_status:'accepted',review:{comments:'Confidential review',submitted_at:'2026-01-01T12:00:00Z'}},
    {assignment_id:2,review_round:2,reviewer:'Other reviewer',status:'assigned',invitation_status:'pending',review:null},
  ]};
  render(<EICStageHistory stage="Peer Review" overview={overview} />);
  expect(screen.getByRole('heading',{name:'Round 1'})).toBeTruthy();
  expect(screen.getByRole('heading',{name:'Round 2 · current round'})).toBeTruthy();
  expect(screen.getByText(/Invitation: Accepted · Assignment: Completed/)).toBeTruthy();
  expect(screen.getByText(/Invitation: Pending · Assignment: Assigned/)).toBeTruthy();
  expect(screen.queryByText('Private reviewer')).toBeNull();
  expect(screen.queryByText('Confidential review')).toBeNull();
});

it('distinguishes missing history, empty history and agreement response', () => {
  const {rerender}=render(<EICStageHistory stage="Initial Editing" overview={{...base,invitations:null}} />);
  expect(screen.getByText('History information is unavailable.')).toBeTruthy();
  expect(screen.getByText('No initial editing submissions are listed.')).toBeTruthy();
  rerender(<EICStageHistory stage="Author Agreement" overview={{...base,author_agreement:{status:'accepted',agreement_version:'v1',responded_at:'2026-01-01T12:00:00Z'}}} />);
  expect(screen.getByText(/Agreement: Accepted · Version: v1/)).toBeTruthy();
  rerender(<EICStageHistory stage="Author Agreement" overview={base} />);
  expect(screen.getByText('Agreement record is unavailable or has not been created.')).toBeTruthy();
});

it('orders dated editing submissions chronologically and leaves undated records last', () => {
  const overview={...base,submissions:[{submission_id:3,status:'pending_author'}, {submission_id:2,status:'editor_approved',created_at:'2026-02-01T00:00:00Z'}, {submission_id:1,status:'pending_author',created_at:'2026-01-01T00:00:00Z'}]};
  render(<EICStageHistory stage="Initial Editing" overview={overview} />);
  const items=screen.getAllByRole('listitem').map(item=>item.textContent);
  expect(items.map(text=>text.match(/Submission #\d/)[0])).toEqual(['Submission #1','Submission #2','Submission #3']);
  expect(items[2]).toContain('Date unavailable');
});

it('offers only a confirmed published document and uses its existing download route', () => {
  const onDownload=vi.fn();
  const formatting={status:'published',publication:{submission_id:42,published_at:'2026-01-01T12:00:00Z'}};
  const {rerender}=render(<EICStageHistory stage="Publication" overview={base} formatting={formatting} onDownload={onDownload} />);
  fireEvent.click(screen.getByRole('button',{name:'Download published document'}));
  expect(onDownload).toHaveBeenCalledWith('/formatting/submissions/42/download');
  rerender(<EICStageHistory stage="Publication" overview={{...base,manuscript:{...base.manuscript,status:'formatting'}}} formatting={formatting} onDownload={onDownload} />);
  expect(screen.queryByRole('button',{name:'Download published document'})).toBeNull();
  expect(screen.getByText('No confirmed publication record is available.')).toBeTruthy();
});

it('renders only source-backed statuses across each stage', () => {
  const {rerender}=render(<EICStageHistory stage="Submission" overview={base} />);
  for (const stage of ['Submission','Initial Screening','Initial Editing','Peer Review','EIC Decision','Author Agreement','Final Editing','Formatting','Publication']) {
    rerender(<EICStageHistory stage={stage} overview={base} />);
    expect(within(screen.getByRole('region',{name:`${stage} history`})).getByRole('heading',{name:'Stage history'})).toBeTruthy();
  }
});

it('distinguishes invitation and review records from document delivery evidence',()=>{
 const overview={...base,assignments:[{assignment_id:9,review_round:8,invitation_status:'accepted',status:'completed',review:{submitted_at:'2026-01-01T00:00:00Z'}}]};
 const {rerender}=render(<EICStageHistory stage="Peer Review" overview={overview}/>);
 expect(screen.getByRole('heading',{name:'Round 8'})).toBeTruthy();
 expect(screen.getByText(/Incoming document binding unavailable/)).toBeTruthy();
 expect(screen.getByText(/Delivery unknown/)).toBeTruthy();
 expect(screen.getByText(/Reviewed document attachment: unavailable/)).toBeTruthy();
 rerender(<EICStageHistory stage="Initial Editing" overview={overview}/>);
 expect(screen.getByText(/Distribution and delivery records are unavailable/)).toBeTruthy();
});

it('reports a matching recorded round binding without claiming delivery',()=>{
 const overview={...base,assignments:[{assignment_id:9,review_round:8,status:'assigned',invitation_status:'accepted',recorded_round_binding:{round_file_id:27,review_round:8,source_kind:'author_revision'}}]};
 const {rerender}=render(<EICStageHistory stage="Peer Review" overview={overview}/>);
 expect(screen.getByText(/Incoming binding #27 recorded/)).toBeTruthy();
 expect(screen.getByText(/file integrity unverified · Delivery unknown/)).toBeTruthy();
 rerender(<EICStageHistory stage="Peer Review" overview={{...overview,assignments:[{...overview.assignments[0],recorded_round_binding:{round_file_id:27,review_round:7}}]}} />);
 expect(screen.getByText(/Incoming document binding unavailable/)).toBeTruthy();
});
