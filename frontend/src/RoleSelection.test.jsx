import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RoleSelection from "./RoleSelection";

afterEach(cleanup);

describe("role selection", () => {
  it("renders four primary roles and routes formatting staff through Editor", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();

    render(<RoleSelection onSelect={onSelect} />);

    expect(screen.getByRole("heading", { name: "G-SUB." })).toBeTruthy();

    const grid = screen.getByLabelText("Choose a sign-in role");

    expect(within(grid).getAllByRole("button")).toHaveLength(4);

    for (const name of [
      "Editor-in-Chief",
      "General / Copy Editor",
      "Peer Reviewer",
      "Author / Submitter",
    ]) {
      expect(within(grid).getByRole("button", { name })).toBeTruthy();
    }

    expect(
      within(grid).queryByRole("button", { name: "Formatter" })
    ).toBeNull();

    await user.click(
      within(grid).getByRole("button", { name: "General / Copy Editor" })
    );

    expect(onSelect).toHaveBeenCalledOnce();
    expect(onSelect).toHaveBeenCalledWith("editor");
  });
});

it('shows only role names on the cards while retaining accessible context', () => {
  render(<RoleSelection onSelect={()=>{}} />);
  const group=screen.getByRole('group',{name:'Choose a sign-in role'});
  expect(within(group).getAllByRole('button')).toHaveLength(4);
  expect(within(group).queryByText(/assigned initial editing|follow progress|review assigned manuscripts|coordinate assignments/i)).toBeNull();
  expect(screen.getByText('Manuscript Management System')).toBeTruthy();
  expect(screen.getByText(/account permissions are determined/i)).toBeTruthy();
  expect(screen.queryByText(/select your role/i)).toBeNull();
  expect(screen.queryByRole('button',{name:'Formatter'})).toBeNull();
});

it('supports keyboard selection for each of the four roles', async () => {
  const onSelect=vi.fn(); const user=userEvent.setup();
  render(<RoleSelection onSelect={onSelect} />);
  for (const [index,id] of ['eic','editor','reviewer','author'].entries()) {
    await user.tab();
    expect(document.activeElement).toBe(screen.getAllByRole('button')[index]);
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenLastCalledWith(id);
  }
});
