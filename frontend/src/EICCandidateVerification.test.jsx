import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import EICCandidateVerification from './EICCandidateVerification';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('requires all eleven checks and sends the exact artifact context', async () => {
  const info = { manuscript_id:8, candidate_id:'c1', review_round:2, artifact_version:3, source_id:4, source_sha256:'a'.repeat(64), prepared_sha256:'b'.repeat(64), method:'docx-v1', processed_at:'2026', human_review:{status:'pending'}, approval:{status:'pending'}, filename_verification:{status:'pending'} };
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
    if (url.endsWith('reconciliation')) return {ok:true,json:async()=>({candidates:[{candidate_id:'c1',stored:true,reserved_at:'2026'}]})};
    if (url.endsWith('/processing')) return {ok:true,json:async()=>info};
    if (url.endsWith('/verify')) { expect(JSON.parse(options.body)).toMatchObject({filename_verified:true,expected_sha256:info.prepared_sha256,expected_artifact_version:3,expected_review_round:2}); return {ok:true,json:async()=>({})}; }
    throw Error(url);
  });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<EICCandidateVerification manuscriptId={8} token="synthetic" />);
  fireEvent.click(screen.getByText('Private reviewer document verification'));
  await screen.findByRole('option', {name:/c1/});
  fireEvent.change(screen.getByLabelText('Candidate'), {target:{value:'c1'}});
  await screen.findByText(/Human verification checklist/);
  expect(screen.getByText('Record human verification').disabled).toBe(true);
  for (const checkbox of screen.getAllByRole('checkbox')) fireEvent.click(checkbox);
  fireEvent.click(screen.getByText('Record human verification'));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/verify'))).toBe(true));
});
