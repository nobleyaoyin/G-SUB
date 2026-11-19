import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import BlindReviewPanel from "./BlindReviewPanel";

vi.mock("./ReviewerInvitationPanel", () => ({ default: ({ invitationPath }) => <div>Invitation path: {invitationPath || "default"}</div> }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("shows default invitation UI when the experimental endpoint is disabled", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ status: 404, ok: false })));
  render(<BlindReviewPanel manuscriptId={3} round={1} status="revised" token="synthetic" />);
  expect(await screen.findByText("Invitation path: default")).toBeTruthy();
});

it("selects a mode and uses the guarded invitation endpoint", async () => {
  let saved = false;
  vi.stubGlobal("fetch", vi.fn(async (_url, opts = {}) => {
    if (opts.method === "PUT") { saved = true; return { ok: true }; }
    return { ok: true, status: 200, json: async () => ({ mode: saved ? "single_blind" : null, revision: saved ? 1 : null, locked: false }) };
  }));
  render(<BlindReviewPanel manuscriptId={3} round={1} status="revised" token="synthetic" />);
  fireEvent.change(await screen.findByLabelText("Review mode"), { target: { value: "single_blind" } });
  fireEvent.click(screen.getByRole("button", { name: "Save review mode" }));
  await waitFor(() => expect(screen.getByText("Invitation path: /assignments/review-invitations")).toBeTruthy());
  expect(screen.getByText(/Mode: Single-Blind/)).toBeTruthy();
});

it("shows locked policy and the required reviewed document", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ mode: "double_blind", revision: 2, locked: true }) })));
  render(<BlindReviewPanel manuscriptId={3} round={1} status="revised" token="synthetic" />);
  expect(await screen.findByText(/not automatically anonymized/)).toBeTruthy();
  expect(screen.queryByLabelText("Review mode")).toBeNull();
});
