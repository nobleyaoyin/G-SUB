import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReviewerInvitationPanel from "./ReviewerInvitationPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("binds an accepted reviewer's approved document", async () => {
  const fetch = vi.fn(async (url, options = {}) => {
    if (options.method === "POST") return { ok: true, status: 200 };
    if (url.endsWith('/summary')) return { ok: true, json: async () => ({ decision_progress: { completed_distinct: 0, required: 2 } }) };
    return { ok: true, json: async () => [{ assignment_id: 7, reviewer_id: 8, review_round: 1, invitation_status: 'accepted', status: 'assigned' }] };
  });
  vi.stubGlobal('fetch', fetch);
  render(<ReviewerInvitationPanel manuscriptId={4} round={1} status="ready_for_peer_review" token="synthetic" artifactBinding />);
  await userEvent.click(await screen.findByRole('button', { name: 'Bind reviewer document' }));
  expect((await screen.findByRole('status')).textContent).toContain('Reviewer document bound');
  expect(fetch.mock.calls.some(([url, opts]) => url.endsWith('/demo-invitations/7/bind-artifact') && opts.method === 'POST')).toBe(true);
});
