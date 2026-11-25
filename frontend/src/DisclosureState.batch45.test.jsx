import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import NotesPanel from './NotesPanel';
import GeneralCommentsPanel from './GeneralCommentsPanel';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

for (const [name, Component, field, submit] of [
  ['notes', NotesPanel, 'New note', 'Add Note'],
  ['comments', GeneralCommentsPanel, 'Add a general comment', 'Add Comment'],
]) {
  it(`${name} retains a pending draft and exposes the failure after collapse`, async () => {
    let finish;
    const fetcher = vi.fn((_url, options = {}) => options.method === 'POST'
      ? new Promise(resolve => { finish = resolve; })
      : Promise.resolve({ok: true, status: 200, json: async () => []}));
    vi.stubGlobal('fetch', fetcher);
    render(<details open><summary>Private context</summary><Component manuscriptId={1} token="synthetic" /></details>);
    const history = screen.getByText('Private context').closest('details');
    const text = screen.getByLabelText(field);
    const user = userEvent.setup();
    await user.type(text, 'Unsaved synthetic content');
    await user.click(within(history).getByRole('button', {name: submit}));
    expect(screen.getByRole('button', {name: 'Saving...'}).disabled).toBe(true);
    fireEvent.submit(text.closest('form'));
    expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
    await user.click(within(history).getByText('Private context'));
    expect(history.open).toBe(false);
    await user.click(within(history).getByText('Private context'));
    expect(text.value).toBe('Unsaved synthetic content');
    expect(screen.getByRole('button', {name: 'Saving...'}).disabled).toBe(true);
    finish({ok: false, status: 422, json: async () => ({detail: 'Synthetic validation error'})});
    expect((await screen.findByRole('alert')).textContent).toContain('Synthetic validation error');
    history.open = false;
    fireEvent(history, new Event('toggle'));
    await waitFor(() => expect(history.open).toBe(true));
    expect(text.value).toBe('Unsaved synthetic content');
  });
}
