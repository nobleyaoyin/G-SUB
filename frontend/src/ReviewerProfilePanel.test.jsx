import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ReviewerProfilePanel from "./ReviewerProfilePanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const existing = { professional_title: "Professor", institution: "Synthetic University", department: null, research_areas: ["Systems"], expertise: ["Security"] };
const response = (profile, ok = true, status = 200) => ({ ok, status, json: async () => ({ profile }) });

it("loads existing fields and saves trimmed self-reported information", async () => {
  const fetchMock = vi.fn(async (_url, options) => options?.method === "PUT" ? response({ ...existing, department: "Computing", expertise: ["Security", "Privacy"] }) : response(existing));
  vi.stubGlobal("fetch", fetchMock); const dirty = vi.fn();
  render(<ReviewerProfilePanel token="synthetic" onDirtyChange={dirty} />);
  expect((await screen.findByLabelText(/Professional Title/)).value).toBe("Professor");
  expect(screen.getByText(/self-reported and is not institutionally verified/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText(/Department/), { target: { value: "Computing" } });
  fireEvent.change(screen.getByLabelText(/Expertise Keywords/), { target: { value: "Security\nPrivacy" } });
  expect(dirty).toHaveBeenLastCalledWith(true);
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect((await screen.findByRole("status")).textContent).toBe("Professional profile saved.");
  const write = fetchMock.mock.calls.find(([, options]) => options?.method === "PUT");
  expect(JSON.parse(write[1].body)).toEqual({ professional_title: "Professor", institution: "Synthetic University", department: "Computing", research_areas: ["Systems"], expertise: ["Security", "Privacy"] });
  expect(dirty).toHaveBeenLastCalledWith(false);
});

it("starts an absent profile blank and rejects invalid lists without a write", async () => {
  const fetchMock = vi.fn(async () => response(null)); vi.stubGlobal("fetch", fetchMock);
  render(<ReviewerProfilePanel token="synthetic" onDirtyChange={vi.fn()} />);
  expect((await screen.findByLabelText(/Professional Title/)).value).toBe("");
  fireEvent.change(screen.getByLabelText(/Research Areas/), { target: { value: Array(13).fill("Area").join("\n") } });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect((await screen.findByRole("alert")).textContent).toContain("up to 12 entries");
  expect(fetchMock.mock.calls.filter(([, options]) => options?.method === "PUT")).toHaveLength(0);
});

it.each([
  ["Professional Title", "x".repeat(101), "at most 100"],
  ["Institution / Affiliation", "Synthetic\u200bInstitute", "no control characters"],
  ["Expertise Keywords", "x".repeat(81), "80 characters"],
])("validates %s before saving", async (label, value, expected) => {
  const fetchMock = vi.fn(async () => response(null)); vi.stubGlobal("fetch", fetchMock);
  render(<ReviewerProfilePanel token="synthetic" onDirtyChange={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText(label, { exact: false }), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect((await screen.findByRole("alert")).textContent).toContain(expected);
  expect(fetchMock.mock.calls.filter(([, options]) => options?.method === "PUT")).toHaveLength(0);
});

it("reports a confirmed server validation rejection without success", async () => {
  vi.stubGlobal("fetch", vi.fn(async (_url, options) => options?.method === "PUT" ? response(null, false, 422) : response(null)));
  render(<ReviewerProfilePanel token="synthetic" onDirtyChange={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText(/Professional Title/), { target: { value: "Researcher" } });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect((await screen.findByRole("alert")).textContent).toContain("invalid");
  expect(screen.queryByText("Professional profile saved.")).toBeNull();
});

it("handles unavailable and failed loads without offering writes", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(null, false, 503)));
  render(<ReviewerProfilePanel token="synthetic" onDirtyChange={vi.fn()} />);
  expect((await screen.findByRole("alert")).textContent).toContain("currently unavailable");
  expect(screen.queryByRole("button", { name: "Save profile" })).toBeNull();
  expect(screen.getByText(/Return to this view to try loading again/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: /reload|refresh|retry loading/i })).toBeNull();
});

it("warns before discarding changes and on browser unload", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(null)));
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  const dirty = vi.fn(); render(<ReviewerProfilePanel token="synthetic" onDirtyChange={dirty} />);
  const input = await screen.findByLabelText(/Institution \/ Affiliation/);
  fireEvent.change(input, { target: { value: "Synthetic Institute" } });
  const unload = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Discard changes" })); expect(input.value).toBe("Synthetic Institute");
  fireEvent.click(screen.getByRole("button", { name: "Discard changes" })); expect(input.value).toBe("");
  expect(confirm).toHaveBeenCalledTimes(2); expect(dirty).toHaveBeenLastCalledWith(false);
});

it("does not claim an ambiguous network write failed or allow a repeat before reload", async () => {
  vi.stubGlobal("fetch", vi.fn(async (_url, options) => { if (options?.method === "PUT") throw new TypeError("network"); return response(null); }));
  render(<ReviewerProfilePanel token="synthetic" onDirtyChange={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText(/Professional Title/), { target: { value: "Researcher" } });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("could not be confirmed"));
  expect(screen.getByRole("button", { name: "Save profile" }).disabled).toBe(true);
});
