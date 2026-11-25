import {afterEach, expect, it} from 'vitest';
import {cleanup, fireEvent, render, screen, within} from '@testing-library/react';
import RoleStatistics from './RoleStatistics';
afterEach(cleanup);
it('shows counts only from provided records, ordered by workflow', () => {
  render(<RoleStatistics items={[{status:'published'},{status:'draft'},{status:'draft'},{status:'ready_for_peer_review'}]} />);
  fireEvent.click(screen.getByText('Statistics'));
  const panel = screen.getByText('Statistics').closest('details');
  expect(within(panel).getByText('4')).toBeTruthy();
  expect(within(panel).getByText('2')).toBeTruthy();
  expect(within(panel).getByText('Currently in review')).toBeTruthy();
  const labels = [...panel.querySelectorAll('.role-statistics-grid span')].map(el => el.textContent);
  expect(labels).toEqual(['Accessible manuscripts', 'Draft', 'Currently in review', 'Published']);
});
it('does not show zero for unavailable data', () => {
  render(<RoleStatistics items={[]} error />);
  fireEvent.click(screen.getByText('Statistics'));
  expect(screen.getByRole('alert').textContent).toMatch(/unavailable/);
  expect(screen.queryByText('0')).toBeNull();
});
it('reports loading instead of counts until records are available', () => {
  render(<RoleStatistics items={[]} loading />);
  fireEvent.click(screen.getByText('Statistics'));
  expect(screen.getByRole('status').textContent).toMatch(/Loading/);
  expect(screen.queryByText('0')).toBeNull();
});
