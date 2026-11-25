import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ManuscriptTimeline from './ManuscriptTimeline';
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const data = id => ({manuscript_id:id, partial_history:true, events:[{key:`event:${id}`, stage:'Submission', description:`Event ${id}`, timestamp:'2026-01-01T00:00:00Z'}]});
it('shows recorded events and keeps roles out of request parameters', async () => {
  const fetcher = vi.fn(async () => ({ok:true,json:async()=>data(1)})); vi.stubGlobal('fetch',fetcher);
  render(<ManuscriptTimeline manuscriptId={1} token="synthetic" />);
  await userEvent.click(screen.getByText('Activity Timeline'));
  expect(await screen.findByText('Event 1')).toBeTruthy();
  expect(screen.queryByText(/Partial history/)).toBeNull();
  expect(screen.queryByText(/Recorded events, newest first/)).toBeNull();
  expect(fetcher.mock.calls[0][0]).toBe('/api/manuscripts/1/timeline');
});
it('does not allow a delayed old response to overwrite a new manuscript', async () => {
  let finish;
  vi.stubGlobal('fetch',vi.fn(url => url.includes('/1/') ? new Promise(resolve => {finish=resolve;}) : Promise.resolve({ok:true,json:async()=>data(2)})));
  const {rerender} = render(<ManuscriptTimeline manuscriptId={1} token="synthetic" />);
  await userEvent.click(screen.getByText('Activity Timeline'));
  rerender(<ManuscriptTimeline manuscriptId={2} token="synthetic" />);
  expect(await screen.findByText('Event 2')).toBeTruthy();
  finish({ok:true,json:async()=>data(1)});
  await waitFor(() => expect(screen.queryByText('Event 1')).toBeNull());
});
it('keeps failures visible without a Retry button and reloads when reopened', async () => {
  vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce({ok:false}).mockResolvedValueOnce({ok:true,json:async()=>data(1)}));
  render(<ManuscriptTimeline manuscriptId={1} token="synthetic" />);
  await userEvent.click(screen.getByText('Activity Timeline'));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByLabelText('Manuscript activity timeline').open).toBe(true);
  expect(screen.queryByRole('button',{name:'Retry'})).toBeNull();
  await userEvent.click(screen.getByText('Activity Timeline'));
  await userEvent.click(screen.getByText('Activity Timeline'));
  expect(await screen.findByText('Event 1')).toBeTruthy();
});
it('shows a recorded undated event without inventing a date', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:1,partial_history:true,
    events:[{key:'legacy:1',stage:'Peer Review',description:'Invitation accepted',timestamp:null}]})})));
  render(<ManuscriptTimeline manuscriptId={1} token="synthetic" />);
  await userEvent.click(screen.getByText('Activity Timeline'));
  expect(await screen.findByText('Invitation accepted')).toBeTruthy();
  expect(screen.getByText('Date unavailable')).toBeTruthy();
  expect(screen.queryByText(/some older events may not have been recorded/)).toBeNull();
});
it('shows an honest empty state for an authorized empty history', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:1,partial_history:true,events:[]})})));
  render(<ManuscriptTimeline manuscriptId={1} token="synthetic" />);
  await userEvent.click(screen.getByText('Activity Timeline'));
  expect(await screen.findByText('No recorded activity is available.')).toBeTruthy();
  expect(screen.queryByRole('listitem')).toBeNull();
});
it('can be collapsed even when activity is unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:false})));
  render(<ManuscriptTimeline manuscriptId={1} token="synthetic" />);
  await userEvent.click(screen.getByText('Activity Timeline'));
  expect(await screen.findByRole('alert')).toBeTruthy();
  await userEvent.click(screen.getByText('Activity Timeline'));
  expect(screen.getByLabelText('Manuscript activity timeline').open).toBe(false);
});
it('orders recorded timestamps newest first, breaks ties by key, and leaves invalid dates last', async () => {
  const events = [
    {key:'missing',stage:'Submission',description:'Missing',timestamp:null},
    {key:'b',stage:'Submission',description:'Tie B',timestamp:'2026-02-01T10:00:00Z'},
    {key:'old',stage:'Submission',description:'Old',timestamp:'2025-01-01T00:00:00Z'},
    {key:'a',stage:'Submission',description:'Tie A',timestamp:'2026-02-01T10:00:00Z'},
    {key:'invalid',stage:'Submission',description:'Invalid',timestamp:'not-a-date'},
  ];
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:1,events})})));
  render(<ManuscriptTimeline manuscriptId={1} token="synthetic" />);
  await userEvent.click(screen.getByText('Activity Timeline'));
  await screen.findByText('Tie A');
  expect(screen.getAllByRole('listitem').map(item=>item.querySelector('strong').textContent)).toEqual(['Tie A','Tie B','Old','Invalid','Missing']);
  expect(screen.getAllByText('Date unavailable')).toHaveLength(2);
});

it('assigns numbers after sorting and preserves order after a refreshed response', async () => {
  const events=[{key:'old',stage:'Submission',description:'Older event',timestamp:'2025-01-01T00:00:00Z'}, {key:'new',stage:'Submission',description:'Newer event',timestamp:'2026-01-01T00:00:00Z'}];
  const fetcher=vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:1,events})}));
  vi.stubGlobal('fetch',fetcher);
  const {rerender}=render(<ManuscriptTimeline manuscriptId={1} token="synthetic" revision={0} />);
  await userEvent.click(screen.getByText('Activity Timeline'));
  await screen.findByText('Newer event');
  const verify=()=>expect(screen.getAllByRole('listitem').map(item=>[item.value,item.querySelector('strong').textContent])).toEqual([[1,'Newer event'],[2,'Older event']]);
  verify();
  rerender(<ManuscriptTimeline manuscriptId={1} token="synthetic" revision={1} />);
  await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(2));
  await screen.findByText('Newer event');
  verify();
});
