import {afterEach, expect, it} from 'vitest';
import {cleanup, render, screen, within} from '@testing-library/react';
import RoleSelection from './RoleSelection';
import SharedSidebar from './SharedSidebar';
import EditorInvitationSummary from './EditorInvitationSummary';
afterEach(cleanup);
it('keeps four chooser cards and explains sign-in and assignment scope',()=>{
  render(<RoleSelection onSelect={()=>{}} />);
  expect(within(screen.getByRole('group',{name:'Choose a sign-in role'})).getAllByRole('button')).toHaveLength(4);
  expect(screen.getByText(/Editor and formatter accounts use General \/ Copy Editor/)).toBeTruthy();
  expect(screen.getByText(/formatting requires an assignment/)).toBeTruthy();
  expect(screen.queryByRole('button',{name:'Formatter'})).toBeNull();
});
it.each([
  ['eic',/coordinate reviewers and make editorial decisions/i],
  ['editor',/authorized initial editing, final editing and formatting assignments/i],
  ['reviewer',/review assigned manuscripts and submit feedback/i],
  ['author',/manage drafts, submit manuscripts, revise and track progress/i],
  ['formatter',/assigned formatting work.*General \/ Copy Editor/i],
])('shows the authenticated %s workspace responsibilities', (role, wording)=>{
  render(<SharedSidebar user={{role,name:'Synthetic'}} onNavigate={()=>{}} />);
  expect(screen.getByText(wording)).toBeTruthy();
});
it.each(['Initial editor','Final editor'])('%s invitation describes an assignment without granting access',stage=>{
  render(<EditorInvitationSummary stage={stage} status="pending" editor="Synthetic" />);
  expect(screen.getByText(/workflow assignments for Editor accounts/)).toBeTruthy();
  expect(screen.getByText(/document access depend on the existing assignment authorization/)).toBeTruthy();
});
