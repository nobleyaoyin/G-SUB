import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import SharedSidebar from "./SharedSidebar";

describe("SharedSidebar", () => {
  afterEach(() => cleanup());

  const user = {
    user_id: 1,
    name: "Synthetic Author",
    role: "author",
  };

  it("shows branding, user and role", () => {
    render(
      <SharedSidebar
        user={user}
        onNavigate={vi.fn()}
        onLogout={vi.fn()}
      />
    );

    expect(screen.getByText("G-SUB")).toBeTruthy();
    expect(screen.getByText("Synthetic Author")).toBeTruthy();
    expect(screen.getByRole("navigation", {
      name: "Dashboard sections",
    })).toBeTruthy();
  });

  it("marks Dashboard active by default", () => {
    render(<SharedSidebar user={user} />);

    expect(
      screen.getByRole("button", { name: "Dashboard" })
        .getAttribute("aria-current")
    ).toBe("page");
  });

  it("calls navigation callbacks", () => {
    const onNavigate = vi.fn();

    render(
      <SharedSidebar user={user} onNavigate={onNavigate} />
    );

    fireEvent.click(screen.getByRole("button", {
      name: "Manuscripts",
    }));

    fireEvent.click(screen.getByRole("button", {
      name: "Notifications",
    }));

    expect(onNavigate).toHaveBeenNthCalledWith(1, "manuscripts");
    expect(onNavigate).toHaveBeenNthCalledWith(2, "notifications");
  });

  it("does not place logout in the sidebar", () => {
    render(<SharedSidebar user={user} />);
    expect(screen.queryByRole("button", { name: "Logout" })).toBeNull();
  });

  it("handles missing user information", () => {
    render(<SharedSidebar />);

    expect(screen.getAllByText("User")).toHaveLength(2);
    expect(screen.getByText("G-SUB")).toBeTruthy();
  });

  it.each(["author", "editor", "reviewer", "eic", "formatter"])("preserves navigation for %s", (role) => {
    render(<SharedSidebar user={{ name: "Synthetic", role }} onNavigate={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Logout" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Manuscripts" })).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Notifications" })).not.toBeNull();
  });

  it("disables navigation when no handler is provided", () => {
    render(<SharedSidebar user={user} />);
    expect(screen.getByRole("button", { name: "Dashboard" }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "Manuscripts" }).disabled).toBe(true);
  });
});
