import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import EICWorkQueue, { groupQueue } from './EICWorkQueue';

afterEach(cleanup);
const item = (id, status) => ({ manuscript_id: id, title: `Paper ${id}`, status });

it('groups each authorized item once and keeps unknown, rejected and revision states distinct', () => {
  const result = groupQueue([item(1,'submitted'), item(1,'submitted'), item(2,'revised'), item(3,'rejected'), item(4,null), item(5,'legacy'), item(6,'formatting'), item(7,'final_editing'), item(8,'initial_editing'), item(9,'revision_required')]);
  expect(result.map(g => [g.name, g.items.length])).toEqual([['Screening',1],['Initial editing',1],['Awaiting author response',1],['Peer review',1],['Final editing',1],['Formatting',1],['Closed or published',1],['Other / unavailable',2]]);
});

it('opens only the selected manuscript and does not assert unverified decision readiness', () => {
  const open = vi.fn();
  render(<EICWorkQueue items={[item(1,'eic_decision_pending'),item(2,'submitted'),item(3,'submitted'),item(4,'submitted')]} state="ready" onOpen={open} unread={{state:'ready',count:2}} onOpenNotifications={vi.fn()} />);
  expect(screen.getByText(/No decision-ready count is inferred/)).toBeTruthy();
  expect(screen.getByRole('button',{name:'Open Paper 4 (manuscript 4) from work queue'})).toBeTruthy();
  expect(screen.getByText('2 unread')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Open Paper 2 (manuscript 2) from work queue'}));
  expect(open).toHaveBeenCalledOnce(); expect(open).toHaveBeenCalledWith(2);
});

it('expands groups and opens recent user notifications without marking them read', () => {
  const open=vi.fn(), bell=vi.fn();
  render(<EICWorkQueue items={[item(1,'submitted')]} state="ready" onOpen={open} onOpenNotifications={bell} unread={{state:'ready',count:1,recent:[{notification_id:1,manuscript_id:1,message:'Synthetic update',is_read:false},{notification_id:2,message:'Account alert',is_read:true}]}} />);
  const group=screen.getByText('Screening (1)').closest('details');
  expect(group.open).toBe(true); fireEvent.click(screen.getByText('Screening (1)')); expect(group.open).toBe(false);
  expect(screen.getByText('Unread:')).toBeTruthy(); expect(screen.getByText('Read:')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Synthetic update'})); expect(open).toHaveBeenCalledWith(1);
  fireEvent.click(screen.getByRole('button',{name:'Account alert'})); expect(bell).toHaveBeenCalledOnce();
});

it('distinguishes loading, failure, empty and notification failure', () => {
  const retry=vi.fn(); const props={items:[],onRetry:retry,onOpenNotifications:vi.fn()};
  const {rerender}=render(<EICWorkQueue {...props} state="loading" unread={null} />);
  expect(screen.getByText('Loading workflow groups…')).toBeTruthy();
  rerender(<EICWorkQueue {...props} state="error" unread={{state:'error'}} />);
  expect(screen.getByText('Notifications unavailable')).toBeTruthy();
  expect(screen.queryByText('0 unread')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Retry work queue'})); expect(retry).toHaveBeenCalledOnce();
  rerender(<EICWorkQueue {...props} state="ready" unread={{state:'ready',count:0}} />);
  expect(screen.getByText('The work queue is empty.')).toBeTruthy();
  expect(within(screen.getByLabelText('EIC work queue')).getByText('0 unread')).toBeTruthy();
});
