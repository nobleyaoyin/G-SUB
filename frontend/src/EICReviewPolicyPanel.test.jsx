import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import EICReviewPolicyPanel from "./EICReviewPolicyPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("EIC selects an explicit mode and sees the selected state", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ state: "missing", mode: null, revision: null }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ state: "selected", mode: "double_blind", revision: 1 }) });
  vi.stubGlobal("fetch", fetchMock);
  render(<EICReviewPolicyPanel manuscriptId={1} token="synthetic" invitationCount={0} />);
  expect(await screen.findByText(/Missing — requires EIC review/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Review mode"), { target: { value: "double_blind" } });
  fireEvent.click(screen.getByText("Save review policy"));
  expect(await screen.findByText(/Selected · Double blind/)).toBeTruthy();
  expect(screen.getByText(/release service is not configured/)).toBeTruthy();
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ mode: "double_blind", expected_revision: null });
});

test("a newly created invitation refreshes policy and hides editing once locked", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ state: "selected", mode: "single_blind", revision: 1 }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ state: "locked", mode: "single_blind", revision: 2 }) });
  vi.stubGlobal("fetch", fetchMock);
  const { rerender } = render(<EICReviewPolicyPanel manuscriptId={1} token="synthetic" invitationCount={0} />);
  expect(await screen.findByText(/Selected · Single blind/)).toBeTruthy();
  rerender(<EICReviewPolicyPanel manuscriptId={1} token="synthetic" invitationCount={1} />);
  await waitFor(() => expect(screen.getByText(/Locked · Single blind/)).toBeTruthy());
  expect(screen.queryByLabelText("Review mode")).toBeNull();
});
