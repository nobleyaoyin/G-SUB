import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import ReviewerManuscriptCard from './ReviewerManuscriptCard';
afterEach(cleanup);
it('uses the Author card structure while retaining authorized Reviewer assignment details', () => {
  const item={assignment_id:4,manuscript_id:8,manuscript_title:'Synthetic',status:'assigned',invitation_status:'accepted',review_round:2,manuscript_status:'ready_for_peer_review'};
  const open=vi.fn();render(<ReviewerManuscriptCard assignment={item} onOpen={open} />);
  const card=screen.getByRole('heading',{name:'Synthetic'}).closest('.manuscript-card');
  expect(card.classList.contains('reviewer-card')).toBe(true);
  expect(card.textContent).toContain('Manuscript #8 · Round 2');
  expect(card.textContent).toContain('Invitation: Accepted');
  expect(card.textContent).toContain('Workflow: Currently in review');
  expect(screen.getByText('Workflow:').tagName).toBe('STRONG');
  expect(screen.getByText('Currently in review').dataset.tone).toBe('active');
  expect(card.querySelector('.status-badge').textContent).toBe('Assigned');
  fireEvent.click(screen.getByRole('button',{name:'Open manuscript'}));expect(open).toHaveBeenCalledWith(item);
});
it('does not invent absent dates or assignment fields', () => {
  render(<ReviewerManuscriptCard assignment={{assignment_id:1,manuscript_id:2}} onOpen={()=>{}} />);
  expect(screen.getByRole('heading',{name:'Manuscript #2'})).toBeTruthy();
  expect(screen.queryByText(/Invitation:|Workflow:|Created:|Updated:/)).toBeNull();
});
it('does not expose a legacy title in the list when the authorized manuscript title is absent', () => {
  render(<ReviewerManuscriptCard assignment={{assignment_id:1,manuscript_id:2,title:'Legacy title'}} onOpen={()=>{}} />);
  expect(screen.getByRole('heading',{name:'Manuscript #2'})).toBeTruthy();
  expect(screen.queryByText('Legacy title')).toBeNull();
});
