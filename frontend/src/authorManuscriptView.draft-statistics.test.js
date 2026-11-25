import { describe, expect, it } from 'vitest';
import { manuscriptGroup } from './authorManuscriptView';

describe('author submission statistics', () => {
  it('does not count retained manuscript drafts as submitted or in progress', () => {
    const records = [{ status: 'draft' }, { status: 'draft' }, { status: 'submitted' }];
    expect(records.filter(item => manuscriptGroup(item.status) === 'progress')).toHaveLength(1);
    expect(records.filter(item => manuscriptGroup(item.status) === 'draft')).toHaveLength(2);
  });
});
