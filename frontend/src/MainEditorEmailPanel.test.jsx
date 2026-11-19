import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import MainEditorEmailPanel from "./MainEditorEmailPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("shows only matching manuscript notifications without claiming email delivery", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [
    { notification_id: 1, manuscript_id: 1, notification_type: "review_invitation_response", message: "Response for A" },
    { notification_id: 2, manuscript_id: 2, notification_type: "review_invitation_response", message: "Response for B" },
  ] }));
  render(<MainEditorEmailPanel token="test-token" manuscriptId={1} />);
  expect(await screen.findByText("Response for A")).toBeTruthy();
  expect(screen.queryByText("Response for B")).toBeNull();
  expect(screen.getByText(/Email delivery status: Unknown/)).toBeTruthy();
});
it("reports an unavailable response without claiming success", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
  render(<MainEditorEmailPanel token="test-token" manuscriptId={1} />);
  expect(await screen.findByRole("alert")).toBeTruthy();
});
it("ignores a delayed response after switching manuscripts", async () => {
  let finish;
  vi.stubGlobal("fetch", vi.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValueOnce({ ok: true, json: async () => [{ notification_id: 2, manuscript_id: 2, notification_type: "review_invitation_response", message: "Response for B" }] }));
  const { rerender } = render(<MainEditorEmailPanel token="test-token" manuscriptId={1} />);
  rerender(<MainEditorEmailPanel token="test-token" manuscriptId={2} />);
  expect(await screen.findByText("Response for B")).toBeTruthy();
  finish({ ok: true, json: async () => [{ notification_id: 1, manuscript_id: 1, notification_type: "review_invitation_response", message: "Response for A" }] });
  await waitFor(() => expect(screen.queryByText("Response for A")).toBeNull());
});
