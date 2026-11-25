import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReviewerInvitationPanel from "./ReviewerInvitationPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mockFetch({ reject = false, empty = false, missing = false } = {}) {
  return vi.fn(async (url, options = {}) => {
    if (options.method === "POST") return { ok: !reject, status: reject ? 409 : 201, json: async () => ({ detail: "Reviewer already assigned" }) };
    if (url.includes("reviewer-directory")) return { ok: true, json: async () => empty ? [] : [
      { reviewer_id: 5, name: "Synthetic Reviewer", email: "reviewer@example.test", selectable: true, invitation_status: null, assignment_status: null, profile: missing ? null : { professional_title: "Professor", institution: "Synthetic University", department: null, research_areas: ["Systems"], expertise: ["Security"], provenance: "self_reported" } },
      { reviewer_id: 6, name: "Already Invited", email: "assigned@example.test", selectable: false, invitation_status: "pending", assignment_status: "assigned" },
    ] };
    if (url.endsWith("/summary")) return { ok: true, json: async () => ({ decision_progress: { completed_distinct: 0, required: 2, policy: "two_reviewers" } }) };
    return { ok: true, json: async () => [] };
  });
}

it("searches, offers accessible single selection and submits the selected reviewer", async () => {
  const fetch = mockFetch(); vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  render(<ReviewerInvitationPanel manuscriptId={4} round={1} status="ready_for_peer_review" token="synthetic" />);
  await user.type(screen.getByLabelText("Search reviewers by name, email or institution"), "reviewer");
  const select = await screen.findByLabelText("Reviewer");
  const option = await screen.findByRole("option", { name: /Synthetic Reviewer/ });
  expect(option.value).toBe("5");
  expect(screen.getByRole("option", { name: /Already Invited/ }).disabled).toBe(true);
  await user.selectOptions(select, "5");
  expect(screen.getByText(/self-reported; not verified/)).toBeTruthy();
  expect(screen.getByText("Synthetic University")).toBeTruthy();
  expect(screen.getByText("Systems")).toBeTruthy();
  expect(screen.getByText("Security")).toBeTruthy();
  expect(screen.getByText("Not provided")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Invite reviewer" }));
  expect((await screen.findByRole("status")).textContent).toContain("Reviewer invitation sent.");
  await waitFor(() => expect(fetch.mock.calls.some(([, opts]) => opts?.method === "POST")).toBe(true));
  const call = fetch.mock.calls.find(([, opts]) => opts?.method === "POST");
  expect(JSON.parse(call[1].body)).toEqual({ manuscript_id: 4, reviewer_id: 5, review_round: 1 });
  await waitFor(() => expect(fetch.mock.calls.filter(([url]) => url.endsWith('/assignments/manuscript/4')).length).toBeGreaterThanOrEqual(2));
  expect(screen.queryByRole('button', { name: /refresh/i })).toBeNull();
});

it("shows empty search results without offering an invitation", async () => {
  vi.stubGlobal("fetch", mockFetch({ empty: true }));
  const user = userEvent.setup(); render(<ReviewerInvitationPanel manuscriptId={4} round={1} status="revised" token="synthetic" />);
  await user.type(screen.getByLabelText("Search reviewers by name, email or institution"), "none");
  expect(await screen.findByText("No matching reviewers.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Invite reviewer" }).disabled).toBe(true);
});

it("does not imply missing profiles were deliberately omitted", async () => {
  vi.stubGlobal("fetch", mockFetch({ missing: true }));
  const user = userEvent.setup(); render(<ReviewerInvitationPanel manuscriptId={4} round={1} status="revised" token="synthetic" />);
  await user.type(screen.getByLabelText("Search reviewers by name, email or institution"), "reviewer");
  await screen.findByRole("option", { name: /Synthetic Reviewer/ });
  await user.selectOptions(screen.getByLabelText("Reviewer"), "5");
  expect(screen.getAllByText(/not provided or unavailable/i).length).toBeGreaterThan(0);
  expect(screen.queryByText(/self-reported; not verified/i)).toBeNull();
});

it("preserves a confirmed duplicate rejection", async () => {
  vi.stubGlobal("fetch", mockFetch({ reject: true }));
  const user = userEvent.setup(); render(<ReviewerInvitationPanel manuscriptId={4} round={1} status="revised" token="synthetic" />);
  await user.type(screen.getByLabelText("Search reviewers by name, email or institution"), "reviewer");
  const select = await screen.findByLabelText("Reviewer");
  await screen.findByRole("option", { name: /Synthetic Reviewer/ });
  await user.selectOptions(select, "5"); await user.click(screen.getByRole("button", { name: "Invite reviewer" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Reviewer already assigned");
});

it("uses the guarded additional-reviewer action for a split", async () => {
  const fetch = mockFetch(); vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  render(<ReviewerInvitationPanel manuscriptId={4} round={1} status="revised" token="synthetic" splitReview={{ classification: "split", can_invite_additional: true }} />);
  await user.type(screen.getByLabelText("Search reviewers by name, email or institution"), "reviewer");
  await screen.findByRole("option", { name: /Synthetic Reviewer/ });
  await user.selectOptions(screen.getByLabelText("Reviewer"), "5");
  await user.click(screen.getByRole("button", { name: "Invite additional reviewer" }));
  await waitFor(() => expect(fetch.mock.calls.some(([url, opts]) => url.endsWith("/assignments/additional-reviewer") && opts?.method === "POST")).toBe(true));
});

it("does not offer a second additional invitation while one is active", () => {
  vi.stubGlobal("fetch", mockFetch());
  render(<ReviewerInvitationPanel manuscriptId={4} round={1} status="revised" token="synthetic" splitReview={{ classification: "split", can_invite_additional: false }} />);
  expect(screen.queryByRole("button", { name: /invite reviewer/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /invite additional reviewer/i })).toBeNull();
});
