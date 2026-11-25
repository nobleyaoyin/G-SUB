import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import App from './App';

vi.mock('./NotificationBell', () => ({ default: () => null }));
vi.mock('./ReviewerProfilePanel', () => ({ default: () => null }));
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('unmounts reviewer A on logout and mounts a fresh reviewer B after login', async () => {
  const headers = new Headers({ 'content-type': 'application/json' });
  const reply = value => ({ ok: true, headers, json: async () => value });
  sessionStorage.setItem('access_token', 'a');
  vi.stubGlobal('fetch', vi.fn(async (url, options = {}) => {
    if (url.endsWith('/users/auth-options')) return reply({ captcha: { provider: 'disabled' }, google: false });
    if (url.endsWith('/users/login')) return reply({ access_token: 'b' });
    const token = options.headers?.Authorization;
    if (url.endsWith('/users/me')) return reply(token === 'Bearer b' ? { user_id: 2, name: 'B', role: 'reviewer' } : { user_id: 1, name: 'A', role: 'reviewer' });
    if (url.endsWith('/assignments/my')) return reply([{ assignment_id: token === 'Bearer b' ? 2 : 1, manuscript_id: token === 'Bearer b' ? 2 : 1, review_round: 1, status: 'assigned', invitation_status: 'accepted', review_file_available: false }]);
    return reply({ manuscript_id: 1, stages: [] });
  }));
  render(<App />);
  fireEvent.click(await screen.findByRole('button', { name: 'Manuscripts' }));
  fireEvent.click((await screen.findByRole('heading', { name: 'Manuscript #1' })).closest('.reviewer-card').querySelector('button'));
  fireEvent.change(screen.getByLabelText(/Review Comments/), { target: { value: 'Private A' } });
  fireEvent.click(screen.getByRole('button', { name: 'User menu' }));
  fireEvent.click(screen.getByRole('button', { name: 'Logout' }));
  await screen.findByLabelText('Choose a sign-in role');
  expect(screen.queryByDisplayValue('Private A')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Peer Reviewer' }));
  fireEvent.change(screen.getByLabelText('Email Address'), { target: { value: 'b@example.test' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'synthetic' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Manuscripts' }));
  expect(await screen.findByRole('heading', { name: 'Manuscript #2' })).toBeTruthy();
  expect(screen.queryByDisplayValue('Private A')).toBeNull();
  await waitFor(() => expect(sessionStorage.getItem('access_token')).toBe('b'));
});
