import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import App from "./App";
import useManuscriptReturn from "./useManuscriptReturn";

function RoleFixture({ registerManuscriptReturn }) {
  const [selected, setSelected] = useState(null);
  const [dirty, setDirty] = useState(false);
  useManuscriptReturn(registerManuscriptReturn, () => {
    if (dirty && !window.confirm("Discard changes?")) return false;
    setSelected(null); setDirty(false); return true;
  });
  return <section data-sidebar-target="manuscripts">
    {selected === null ? <><button onClick={() => setSelected("A")}>Open A</button><button onClick={() => setSelected("B")}>Open B</button></> :
      <><h2>Manuscript {selected}</h2><input aria-label="Draft" onChange={() => setDirty(true)} /></>}
  </section>;
}
vi.mock("./AuthorDashboard", () => ({ default: RoleFixture }));
vi.mock("./EditorDashboard", () => ({ default: RoleFixture }));
vi.mock("./EICDashboard", () => ({ default: RoleFixture }));
vi.mock("./ReviewerDashboard", () => ({ default: RoleFixture }));
vi.mock("./FormattingPanel", () => ({ default: RoleFixture }));
vi.mock("./NotificationBell", () => ({ default: () => <button className="notification-bell">Bell</button> }));
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it.each(["author", "editor", "eic", "reviewer", "formatter"])("returns %s to its list and respects cancellation", async role => {
  sessionStorage.setItem("access_token", "synthetic");
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, headers: new Headers({ "content-type": "application/json" }), json: async () => ({ name: "Synthetic", role }) })));
  vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Open A" }));
  fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "unsaved" } });
  const nav = screen.getByLabelText("Main navigation");
  fireEvent.click(within(nav).getByRole("button", { name: "Manuscripts" }));
  expect(screen.getByRole("heading", { name: "Manuscript A" })).toBeTruthy();
  expect(screen.getByLabelText("Draft").value).toBe("unsaved");
  fireEvent.click(within(nav).getByRole("button", { name: "Manuscripts" }));
  fireEvent.click(await screen.findByRole("button", { name: "Open B" }));
  expect(screen.queryByText("Manuscript A")).toBeNull();
  expect(screen.getByText("Manuscript B")).toBeTruthy();
  fireEvent.click(within(nav).getByRole("button", { name: "Manuscripts" }));
  fireEvent.click(await screen.findByRole("button", { name: "Open A" }));
  expect(screen.getByText("Manuscript A")).toBeTruthy();
  expect(screen.queryByText("Manuscript B")).toBeNull();
});
