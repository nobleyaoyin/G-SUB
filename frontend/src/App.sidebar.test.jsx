import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import App from "./App";

vi.mock("./AuthorDashboard", () => ({ default: ({accountControl}) => <main><button className="notification-bell" aria-expanded="false">Bell</button>{accountControl}<section data-sidebar-target="manuscripts">Author manuscripts</section></main> }));
vi.mock("./EditorDashboard", () => ({ default: ({accountControl}) => <main><button className="notification-bell" aria-expanded="false">Bell</button>{accountControl}<section data-sidebar-target="manuscripts">Editor manuscripts</section></main> }));
vi.mock("./ReviewerDashboard", () => ({ default: ({ onProfileDirtyChange, accountControl }) => <main><button className="notification-bell" aria-expanded="false">Bell</button>{accountControl}<section data-sidebar-target="manuscripts">Reviewer manuscripts</section><button onClick={() => onProfileDirtyChange(true)}>Simulate unsaved profile</button></main> }));
vi.mock("./EICDashboard", () => ({ default: ({accountControl}) => <main><button className="notification-bell" aria-expanded="false">Bell</button>{accountControl}<section data-sidebar-target="manuscripts">EIC manuscripts</section></main> }));
vi.mock("./FormattingPanel", () => ({ default: () => <section data-sidebar-target="manuscripts">Formatter assignments</section> }));
vi.mock("./NotificationBell", () => ({ default: () => <button className="notification-bell" aria-expanded="false">Bell</button> }));

afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it.each(["author", "editor", "reviewer", "eic", "formatter"])("restores %s and logs out through the account menu", async role => {
  sessionStorage.setItem("access_token", "synthetic");
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, headers: new Headers({ "content-type": "application/json" }), json: async () => ({ name: "Synthetic", role }) })));
  render(<App />);
  const nav = await screen.findByLabelText("Main navigation");
  expect(within(nav).queryByRole("button", { name: "Logout" })).toBeNull();
  {
    const bell = screen.getByRole("button", { name: "Bell" });
    const clicked = vi.fn(); bell.addEventListener("click", clicked);
    fireEvent.click(within(nav).getByRole("button", { name: "Notifications" }));
    expect(clicked).not.toHaveBeenCalled();
    expect(within(nav).getByRole("button", { name: "Notifications" }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(within(nav).getByRole("button", { name: "Manuscripts" }));
    expect(within(nav).getByRole("button", { name: "Manuscripts" }).getAttribute("aria-current")).toBe("page");
  }
  fireEvent.click(screen.getByRole("button", { name: "User menu" }));
  fireEvent.click(screen.getByRole("button", { name: "Logout" }));
  await waitFor(() => expect(sessionStorage.getItem("access_token")).toBeNull());
  expect(await screen.findByLabelText("Choose a sign-in role")).toBeTruthy();
});

it("confirms before logging out with unsaved reviewer changes", async () => {
  sessionStorage.setItem("access_token", "synthetic");
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, headers: new Headers({ "content-type": "application/json" }), json: async () => ({ name: "Synthetic", role: "reviewer" }) })));
  vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Simulate unsaved profile" }));
  fireEvent.click(screen.getByRole("button", { name: "User menu" }));
  fireEvent.click(screen.getByRole("button", { name: "Logout" }));
  expect(sessionStorage.getItem("access_token")).toBe("synthetic");
  fireEvent.click(screen.getByRole("button", { name: "Logout" }));
  await waitFor(() => expect(sessionStorage.getItem("access_token")).toBeNull());
});
