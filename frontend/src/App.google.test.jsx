import { StrictMode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import App from './App';

vi.mock('./AuthorDashboard', () => ({default: () => <main>Synthetic author dashboard</main>}));
afterEach(() => { cleanup(); sessionStorage.clear(); window.history.replaceState({}, '', '/'); vi.unstubAllGlobals(); });

it('shows the Google option only when configured', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({captcha:{provider:'disabled'},google:true})})));
  render(<App />);
  fireEvent.click(screen.getByRole('button',{name:'Author / Submitter'}));
  expect(await screen.findByRole('button',{name:'Continue with Google'})).toBeTruthy();
});

it('exchanges a callback once under StrictMode and preserves role checks', async () => {
  window.history.replaceState({}, '', '/google-callback');
  sessionStorage.setItem('google_selected_role','author');
  const fetch=vi.fn(async url => url.endsWith('/google/exchange')
    ? {ok:true,json:async()=>({access_token:'synthetic-token'})}
    : url.endsWith('/users/me')
      ? {ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>({name:'Synthetic',role:'author'})}
      : {ok:true,json:async()=>({captcha:{provider:'disabled'},google:true})});
  vi.stubGlobal('fetch',fetch);
  render(<StrictMode><App /></StrictMode>);
  expect(await screen.findByText('Synthetic author dashboard')).toBeTruthy();
  await waitFor(()=>expect(sessionStorage.getItem('access_token')).toBe('synthetic-token'));
  expect(fetch.mock.calls.filter(([url])=>url.endsWith('/google/exchange'))).toHaveLength(1);
});
