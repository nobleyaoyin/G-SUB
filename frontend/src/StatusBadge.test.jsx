import {cleanup, render, screen} from '@testing-library/react';
import {afterEach, expect, it} from 'vitest';
import StatusBadge from './StatusBadge';

afterEach(cleanup);
it.each([
  ['draft', 'Draft', 'neutral'], ['formatting', 'Formatting', 'active'],
  ['final_editing', 'Final editing', 'active'], ['initial_editing', 'Initial editing', 'active'],
  ['ready_for_peer_review', 'Currently in review', 'active'],
  ['revision_required', 'Revision required', 'attention'], ['accepted', 'Accepted', 'positive'],
  ['submitted', 'Submitted', 'active'], ['initial_screening', 'Initial screening', 'neutral'],
  ['revised', 'Revised', 'active'], ['eic_decision_pending', 'EIC decision pending', 'neutral'],
  ['awaiting_author_agreement', 'Awaiting author agreement', 'neutral'], ['published', 'Published', 'positive'],
  ['completed', 'Completed', 'positive'], ['unknown_future_status', 'Unknown future status', 'neutral'],
])('displays %s without changing its identifier', (status, label, tone) => {
  render(<StatusBadge status={status} />);
  expect(screen.getByText(label).dataset.tone).toBe(tone);
});
