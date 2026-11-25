import {expect, it} from 'vitest';
import {selectRoleItems} from './RoleListControls';

it('combines authorized records with search, stage, sub-stage and sorting', () => {
  const items = [
    {manuscript_id: 1, title: 'Beta revision', status: 'revised'},
    {manuscript_id: 2, title: 'Alpha revision', status: 'revised'},
    {manuscript_id: 3, title: 'Other revision', status: 'revision_required'},
    {manuscript_id: 4, title: 'Draft revision', status: 'draft'},
  ];
  const filter = 'stage:Peer Review|status:revised';
  expect(selectRoleItems(items, 'revision', filter, 'title').map(item => item.manuscript_id)).toEqual([2, 1]);
  expect(selectRoleItems(items, '1', filter, 'title').map(item => item.manuscript_id)).toEqual([1]);
  expect(selectRoleItems(items, '', 'stage:Peer Review', 'title').map(item => item.manuscript_id)).toEqual([2, 1, 3]);
  expect(selectRoleItems(items, '', '', 'title')).toHaveLength(4);
});
