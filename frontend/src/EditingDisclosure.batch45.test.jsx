import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import InitialEditingPanel from './InitialEditingPanel';
import FinalEditingPanel from './FinalEditingPanel';

vi.mock('./OnlineDocumentEditor', () => ({default: () => null}));
vi.mock('./OnlineDocxEditor', () => ({default: () => null}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const old = {submission_id: 10, status: 'author_revision_requested', comments: 'Earlier version'};
const current = {submission_id: 11, status: 'author_revision_requested', comments: 'Current version'};
const cases = [
  ['initial', InitialEditingPanel, {manuscript_id: 7, title: 'Synthetic', status: 'initial_editing',
    invitation: {status: 'accepted', editor: 'Synthetic editor'}, submissions: [current, old]},
   'Earlier initial-editing documents', 'Download initial-editing document', 'Submit initial-editing document'],
  ['final', FinalEditingPanel, {manuscript_id: 7, title: 'Synthetic', status: 'accepted',
    manuscript_status: 'final_editing', invitation_id: 5, submissions: [current, old]},
   'Earlier final-editing documents', 'Download final editing document', 'Submit final editing document'],
];

for (const [stage, Component, item, label, downloadLabel, submitLabel] of cases) {
  it(`${stage} keeps the current action visible and retains a dirty form across history and failure`, async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url, options = {}) => options.method === 'POST'
      ? {ok: false, status: 422, json: async () => ({detail: 'Synthetic validation failure'})}
      : {ok: true, json: async () => [item]}));
    render(<Component role="editor" token="synthetic" onChanged={async () => {}} />);
    const history = (await screen.findByText(label)).closest('details');
    expect(history.open).toBe(false);
    const downloads = screen.getAllByRole('button', {name: downloadLabel});
    expect(downloads).toHaveLength(2);
    expect(downloads[0].closest('details')).toBeNull();
    expect(downloads[1].closest('details')).toBe(history);
    const user = userEvent.setup();
    const file = new File(['synthetic'], 'draft.txt', {type: 'text/plain'});
    const input = screen.getByLabelText('PDF, DOCX, DOC, or UTF-8 TXT file');
    await user.upload(input, file);
    await user.type(screen.getByLabelText('Editing comments'), 'Unsaved editing text');
    await user.click(within(history).getByText(label));
    expect(history.open).toBe(true);
    expect(screen.getAllByRole('button', {name: downloadLabel})).toHaveLength(2);
    await user.click(within(history).getByText(label));
    expect(history.open).toBe(false);
    expect(input.files[0]).toBe(file);
    expect(screen.getByLabelText('Editing comments').value).toBe('Unsaved editing text');
    fireEvent.submit(screen.getByRole('button', {name: submitLabel}).closest('form'));
    expect((await screen.findByRole('alert')).textContent).toContain('Synthetic validation failure');
    expect(history.open).toBe(false);
    expect(input.files[0]).toBe(file);
    expect(screen.getByLabelText('Editing comments').value).toBe('Unsaved editing text');
    expect(screen.getByRole('button', {name: submitLabel})).toBeTruthy();
  });
}
