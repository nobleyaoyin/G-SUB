import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import RoleOverview from './RoleOverview';
import {selectRoleItems} from './RoleListControls';
afterEach(cleanup);
it('uses supplied role records for summary and opens the chosen manuscript', () => {
 const open=vi.fn(), navigate=vi.fn();
 render(<RoleOverview label="Reviewer" items={[{assignment_id:4,manuscript_id:8,status:'assigned',title:'Synthetic'}]} onOpen={open} onNavigate={navigate} />);
 expect(screen.getByText('Review assignments')).toBeTruthy();
 expect(screen.getByText('Review assignments').parentElement.textContent).toContain('1');
 fireEvent.click(screen.getByRole('button',{name:'Open manuscript'}));
 expect(open).toHaveBeenCalledWith(expect.objectContaining({manuscript_id:8,assignment_id:4}));
 fireEvent.click(screen.getByRole('button',{name:'View all manuscripts'}));
 expect(navigate).toHaveBeenCalledWith('manuscripts');
});
it('places Reviewer statistics in a single sidebar and reuses the Author action style', () => {
 render(<RoleOverview label="Reviewer" items={[{assignment_id:4,manuscript_id:8,status:'assigned',title:'Synthetic'}]} onOpen={()=>{}} onNavigate={()=>{}} />);
 const overview=screen.getByRole('region',{name:'Reviewer overview'});
 const sidebar=screen.getByLabelText('Reviewer overview statistics');
 expect(sidebar.parentElement).toBe(overview);
 expect(overview.querySelectorAll('summary')).toHaveLength(1);
 expect(screen.getByRole('button',{name:'Open manuscript'}).classList.contains('download-button')).toBe(true);
});
it('uses Author-style rows while preserving Reviewer assignment details and navigation', () => {
 const open=vi.fn(), navigate=vi.fn();
 const items=[{assignment_id:4,manuscript_id:8,manuscript_title:'Synthetic title',review_round:2,status:'assigned',invitation_status:'accepted',manuscript_status:'ready_for_peer_review'},
   {assignment_id:5,manuscript_id:9,review_round:1,status:'completed',invitation_status:'accepted',manuscript_status:'revision_required'}];
 render(<RoleOverview label="Reviewer" items={items} onOpen={open} onNavigate={navigate} />);
 const list=screen.getByRole('list');
 expect(list.classList.contains('author-recent-list')).toBe(true);
 const rows=within(list).getAllByRole('listitem');
 expect(rows).toHaveLength(2);
 expect(rows[0].textContent).toContain('Synthetic title');
 expect(rows[0].textContent).toContain('Manuscript #8 · Round 2');
 expect(rows[0].textContent).toContain('Invitation: Accepted');
 expect(within(rows[0]).getByText('Assigned').dataset.tone).toBe('active');
 expect(within(rows[0]).getByText('Currently in review').dataset.tone).toBe('active');
 expect(within(rows[1]).getByText('Completed').dataset.tone).toBe('positive');
 expect(within(rows[1]).getByText('Revision required').dataset.tone).toBe('attention');
 expect(rows[1].textContent).toContain('Manuscript #9');
 fireEvent.click(within(rows[1]).getByRole('button',{name:'Open manuscript'}));
 expect(open).toHaveBeenCalledWith(items[1]);
 fireEvent.click(screen.getByRole('button',{name:'View all manuscripts'}));
 expect(navigate).toHaveBeenCalledWith('manuscripts');
});
it('filters and sorts only supplied role records', () => {
 const items=[{manuscript_id:2,title:'Beta',status:'assigned',updated_at:'2026-01-02'},{manuscript_id:1,title:'Alpha',status:'completed',updated_at:'2026-01-01'}];
 expect(selectRoleItems(items,'1','','recent').map(x=>x.manuscript_id)).toEqual([1]);
 expect(selectRoleItems(items,'','assigned','title').map(x=>x.manuscript_id)).toEqual([2]);
 expect(selectRoleItems(items,'','','oldest').map(x=>x.manuscript_id)).toEqual([1,2]);
 expect(selectRoleItems(items,'','','title').map(x=>x.manuscript_id)).toEqual([1,2]);
});
it('shows status counts only inside the statistics panel when it owns the panel', () => {
 render(<RoleOverview label="EIC" items={[{manuscript_id:1,status:'submitted'}]} onOpen={()=>{}} onNavigate={()=>{}} />);
 expect(screen.getAllByText('Statistics')).toHaveLength(1);
 expect(screen.queryByRole('region',{name:'Status overview'})).toBeNull();
 const statistics=screen.getByText('Statistics').closest('details');
 expect(within(statistics).getByText('Submitted').parentElement.textContent).toContain('1');
});
it('places EIC overview statistics in a sidebar beside its manuscript content', () => {
 render(<RoleOverview label="EIC" items={[{manuscript_id:1,status:'submitted'}]} onOpen={()=>{}} onNavigate={()=>{}} />);
 const overview=screen.getByRole('region',{name:'EIC overview'});
 expect(overview.classList.contains('eic-overview-layout')).toBe(true);
 expect(screen.getByLabelText('EIC overview statistics').parentElement).toBe(overview);
 expect(within(screen.getByLabelText('EIC overview statistics')).getByText('Statistics')).toBeTruthy();
});
it('keeps one statistics panel with truthful loading and error states', () => {
 const {rerender}=render(<RoleOverview label="EIC" items={[]} loading onOpen={()=>{}} onNavigate={()=>{}} />);
 expect(screen.getAllByText('Statistics')).toHaveLength(1);
 expect(screen.getByText('Loading statistics…')).toBeTruthy();
 rerender(<RoleOverview label="EIC" items={[]} error onOpen={()=>{}} onNavigate={()=>{}} />);
 expect(screen.getAllByText('Statistics')).toHaveLength(1);
 expect(screen.getByText('Statistics are unavailable.')).toBeTruthy();
 expect(screen.queryByText('Accessible manuscripts')).toBeNull();
});
it('does not render a second status summary when the Editor supplies its own statistics panel', () => {
 render(<RoleOverview label="Editor" hideStatistics items={[{manuscript_id:1,status:'revision_required'}]} onOpen={()=>{}} onNavigate={()=>{}} />);
 expect(screen.queryByRole('region',{name:'Status overview'})).toBeNull();
 expect(screen.queryByText('revision required')).toBeNull();
});
