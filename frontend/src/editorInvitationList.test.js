import {expect, it} from 'vitest';
import {pendingEditorInvitations} from './editorInvitationList';
it('keeps pending invitation summaries isolated, deduplicated and free of history fields', () => {
  const initial=[{manuscript_id:3,title:'Initial invitation',status:'initial_editor_invited',invitation:{status:'pending'},submissions:[{comments:'private'}]}, {manuscript_id:4,status:'initial_editor_invited',invitation:{status:'revoked'}}, {manuscript_id:0,status:'initial_editing',invitation:{status:'pending'}}];
  const final=[{manuscript_id:3,title:'same',status:'pending',manuscript_status:'final_editing'}, {manuscript_id:5,title:'Final invitation',status:'pending',manuscript_status:'final_editing'}, {manuscript_id:6,status:'revoked',manuscript_status:'final_editing'}, {manuscript_id:7,status:'pending',manuscript_status:'draft'}];
  const result=pendingEditorInvitations(initial,final);
  expect(result.map(item=>item.manuscript_id)).toEqual([3,5]);
  expect(result[0].invitationKinds).toEqual(['initial','final']);
  expect(result[0].invitationOnly).toBe(true);
  expect(result[0]).not.toHaveProperty('submissions');
  expect(result[1]).toMatchObject({status:'final_editing',invitationKinds:['final']});
});
