import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import ManuscriptProgress from './ManuscriptProgress';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('browses all ten workspaces from the single expandable timeline', async () => {
  const browse = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:9,current_stage:'Initial Screening',review_round:1,stages:[{name:'Initial Screening',state:'current',steps:[]}]})})));
  render(<ManuscriptProgress manuscriptId={9} token="synthetic" onBrowseStage={browse} selectedStage="Initial Screening" />);
  const timeline=await screen.findByRole('list',{name:'Workflow timeline'});
  expect(within(timeline).getAllByRole('listitem')).toHaveLength(10);
  const proofing=within(timeline).getByText('Proofing').closest('details');
  fireEvent.click(within(proofing).getByText('Proofing'));
  fireEvent.click(within(proofing).getByRole('button',{name:'View Proofing workspace'}));
  expect(browse).toHaveBeenCalledWith('Proofing');
  const milestone=within(timeline).getByText('Publication').closest('details');
  fireEvent.click(within(milestone).getByText('Publication'));
  fireEvent.click(within(milestone).getByRole('button',{name:'View Publication workspace'}));
  expect(browse).toHaveBeenCalledWith('Publication');
  expect(within(milestone).getByText('Status unavailable')).toBeTruthy();
});

it('explains that stage browsing is unavailable when the role has no workspace handler', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:9,current_stage:'Submission',review_round:1,stages:[{name:'Submission',state:'current',steps:[]}]})})));
  render(<ManuscriptProgress manuscriptId={9} token="synthetic" />);
  const timeline = await screen.findByRole('list',{name:'Workflow timeline'});
  const details = within(timeline).getByText('Submission').closest('details');
  fireEvent.click(within(details).getByText('Submission'));
  expect(within(details).getByText(/Stage workspace browsing is unavailable from this view/)).toBeTruthy();
  expect(within(details).queryByRole('button',{name:/View .* workspace/})).toBeNull();
});
