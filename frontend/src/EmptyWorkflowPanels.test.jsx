import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { waitFor } from '@testing-library/react';
import AuthorAgreementPanel from './AuthorAgreementPanel';
import InitialEditingPanel from './InitialEditingPanel';
import FinalEditingPanel from './FinalEditingPanel';
import FormattingPanel from './FormattingPanel';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('hides empty non-formatter workflow panels', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true, json:async () => []})));
  render(<><AuthorAgreementPanel token="synthetic" /><InitialEditingPanel role="author" token="synthetic" /><FinalEditingPanel role="author" token="synthetic" /><FormattingPanel role="author" token="synthetic" /></>);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4));
  expect(screen.queryByRole('region', {name:'Author agreements'})).toBeNull();
  expect(screen.queryByRole('region', {name:'Initial editing workflow'})).toBeNull();
  expect(screen.queryByRole('region', {name:'Final editing workflow'})).toBeNull();
  expect(screen.queryByRole('region', {name:'Formatting workflow'})).toBeNull();
});

it('keeps a load failure visible when there are no items', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:false, status:503})));
  render(<InitialEditingPanel role="author" token="synthetic" />);
  expect((await screen.findByRole('alert')).textContent).toContain('Could not load initial editing');
});

it('retains the formatter empty assignment list', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true, json:async () => []})));
  render(<FormattingPanel role="formatter" token="synthetic" />);
  expect(await screen.findByText('No formatting assignments.')).toBeTruthy();
});

it('hides an EIC formatting section before the stage begins', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => ({ok:true, json:async () => url.endsWith('/formatters') ? [] : {status:'ready_for_peer_review', invitations:[], submissions:[], publication:null}})));
  render(<FormattingPanel role="eic" token="synthetic" manuscriptId={3} />);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole('region', {name:'Formatting workflow'})).toBeNull();
});
