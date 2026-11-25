import {expect, it} from 'vitest';
import {compareWorkflowStatuses, matchesWorkflowFilter, workflowStageLabel, workflowStatusLabel} from './workflowStatus';
import {notificationTitle} from './notificationTitle';
it('orders known statuses by their existing workflow and preserves unknown statuses', () => {
  expect(['published', 'ready_for_peer_review', 'draft', 'formatting', 'unknown'].sort(compareWorkflowStatuses))
    .toEqual(['draft', 'ready_for_peer_review', 'formatting', 'published', 'unknown']);
  expect(workflowStatusLabel('ready_for_peer_review')).toBe('Currently in review');
  expect(workflowStatusLabel('revision_required')).toBe('Revision required');
});
it.each([
  ['submitted','Submitted'], ['initial_scan_passed','Initial scan passed'],
  ['initial_editing','Initial editing'], ['revision_required','Revision required'],
  ['revised','Revised'], ['awaiting_author_agreement','Awaiting author agreement'],
  ['final_editing','Final editing'], ['formatting','Formatting'],
  ['ready_for_peer_review','Currently in review'], ['eic_approved','EIC approved'],
  ['pdf_docx_doc_txt_api_ai','PDF DOCX DOC TXT API AI'], ['unknown_status','Unknown status'],
])('formats %s for display without changing its identifier', (raw, expected) => {
  expect(workflowStatusLabel(raw)).toBe(expected);
  expect(matchesWorkflowFilter({status: raw}, raw)).toBe(true);
});
it('keeps stage keys and acronyms intact while displaying sentence case', () => {
  expect(workflowStageLabel('Initial Screening')).toBe('Initial screening');
  expect(workflowStageLabel('EIC Decision')).toBe('EIC decision');
  expect(notificationTitle('eic_decision_recorded')).toBe('EIC decision recorded');
  expect(notificationTitle('pdf_proof_ready')).toBe('PDF proof ready');
  expect(notificationTitle('g_sub_release')).toBe('G-SUB release');
  expect(workflowStatusLabel(null)).toBe('Status unavailable');
});
