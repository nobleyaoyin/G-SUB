import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import FormattingPanel from './FormattingPanel';
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('shows the authorized timeline for the selected accepted formatter assignment', async () => {
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/progress')
    ? {manuscript_id:8,review_round:1,current_stage:'Formatting',next_action:'Review formatting',stages:[{name:'Formatting',state:'current'}]}
    : [{manuscript_id:8,title:'Synthetic',status:'formatting',invitations:[{invitation_id:5,formatter:'Synthetic',status:'accepted'}],submissions:[]}]})));
  render(<FormattingPanel role="formatter" token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
  expect(await screen.findByRole('list',{name:'Workflow timeline'})).toBeTruthy();
  expect(screen.getByRole('button',{name:'Download approved final edit'})).toBeTruthy();
  expect(screen.queryByRole('button',{name:/refresh/i})).toBeNull();
});
