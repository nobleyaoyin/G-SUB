import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FinalEditingPanel from "./FinalEditingPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("offers TXT final-edit uploads and sends the selected synthetic file", async () => {
  const item = { manuscript_id: 7, title: "Synthetic", status: "accepted", manuscript_status: "final_editing", invitation_id: 2, submissions: [] };
  const fetchMock = vi.fn(async (_url, options = {}) => ({
    ok: true, json: async () => options.method === "POST" ? {} : [item],
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<FinalEditingPanel role="editor" token="synthetic" onChanged={async () => {}} />);
  const input = await screen.findByLabelText("PDF, DOCX, DOC, or UTF-8 TXT file");
  expect(input.accept).toContain(".txt");
  expect(input.accept).toContain(".docx");
  expect(input.accept).toContain(".doc");
  const user = userEvent.setup();
  const file = new File(["synthetic text"], "final.txt", { type: "text/plain" });
  await user.upload(input, file);
  await user.type(screen.getByLabelText("Editing comments"), "Edited");
  fireEvent.submit(screen.getByRole("button", { name: "Submit final editing document" }).closest("form"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  const write = fetchMock.mock.calls.find(([, options]) => options?.method === "POST");
  expect(write[1].body.get("file")).toBe(file);
  expect(write[1].body.get("comments")).toBe("Edited");
  expect((await screen.findByRole("status")).textContent).toContain("Action completed.");
});
