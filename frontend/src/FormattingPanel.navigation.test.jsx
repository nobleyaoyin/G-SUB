import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import FormattingPanel from './FormattingPanel';
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('opens one formatter manuscript at a time', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>[1,2].map(id=>({manuscript_id:id,title:`Paper ${id}`,status:'formatting',invitations:[],submissions:[]}))})));
  render(<FormattingPanel role="formatter" token="synthetic" />);
  const card=(await screen.findByText('#1 Paper 1')).closest('article');
  fireEvent.click(within(card).getByRole('button',{name:'Open manuscript'}));
  expect(screen.getByText('#1 Paper 1').closest('[data-workspace=selected]')).toBeTruthy();expect(screen.queryByText('#2 Paper 2')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Back to Manuscripts'}));
  expect(screen.getByText('#2 Paper 2')).toBeTruthy();
  expect(screen.queryByRole('button',{name:/refresh/i})).toBeNull();
});
it('opens only an authorized notification target and allows returning to the list', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>[1,2].map(id=>({manuscript_id:id,title:`Paper ${id}`,status:'formatting',invitations:[],submissions:[]}))})));
  const {rerender}=render(<FormattingPanel role="formatter" token="synthetic" navigationTarget={{manuscriptId:2}} />);
  expect(await screen.findByRole('button',{name:'Back to Manuscripts'})).toBeTruthy();
  expect(screen.queryByText('#1 Paper 1')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Back to Manuscripts'}));
  expect(await screen.findByText('#1 Paper 1')).toBeTruthy();
  rerender(<FormattingPanel role="formatter" token="synthetic" navigationTarget={{manuscriptId:99}} />);
  expect(screen.queryByRole('button',{name:'Back to Manuscripts'})).toBeNull();
});

it('preserves unsaved changes when navigation is cancelled', async () => {
  vi.stubGlobal('confirm', vi.fn(() => false));

  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    json: async () => [1, 2].map(id => ({
      manuscript_id: id,
      title: `Paper ${id}`,
      status: 'formatting',
      invitations: [{
        invitation_id: id * 10,
        formatter: 'Formatter',
        status: 'accepted',
      }],
      submissions: [],
    })),
  })));

  const { rerender } = render(
    <FormattingPanel role="formatter" token="synthetic" />
  );

  const card = (await screen.findByText('#1 Paper 1')).closest('article');

  fireEvent.click(
    within(card).getByRole('button', { name: 'Open manuscript' })
  );

  const comments = await screen.findByLabelText('Comments');
  expect(screen.getByText('Your formatting invitation is accepted. Current submission eligibility is unconfirmed.')).toBeTruthy();
  fireEvent.change(comments, { target: { value: 'Keep this draft.' } });

  rerender(
    <FormattingPanel
      role="formatter"
      token="synthetic"
      navigationTarget={{ manuscriptId: 2 }}
    />
  );

  expect(window.confirm).toHaveBeenCalledOnce();
  expect(screen.getByText('#1 Paper 1')).toBeTruthy();
  expect(screen.queryByText('#2 Paper 2')).toBeNull();
  expect(screen.getByLabelText('Comments').value).toBe('Keep this draft.');
});

it('preserves unsaved changes when returning to the manuscript list is cancelled', async () => {
  vi.stubGlobal('confirm', vi.fn(() => false));

  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    json: async () => [1, 2].map(id => ({
      manuscript_id: id,
      title: `Paper ${id}`,
      status: 'formatting',
      invitations: [{
        invitation_id: id * 10,
        formatter: 'Formatter',
        status: 'accepted',
      }],
      submissions: [],
    })),
  })));

  render(<FormattingPanel role="formatter" token="synthetic" />);

  const card = (await screen.findByText('#1 Paper 1')).closest('article');

  fireEvent.click(
    within(card).getByRole('button', { name: 'Open manuscript' })
  );

  const comments = await screen.findByLabelText('Comments');
  fireEvent.change(comments, { target: { value: 'Do not discard.' } });

  fireEvent.click(
    screen.getByRole('button', { name: 'Back to Manuscripts' })
  );

  expect(window.confirm).toHaveBeenCalledOnce();
  expect(screen.getByText('#1 Paper 1')).toBeTruthy();
  expect(screen.getByLabelText('Comments').value).toBe('Do not discard.');
});


it('uses the registered formatter return handler without discarding cancelled input', async () => {
  vi.stubGlobal('confirm',vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true));
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[1,2].map(id=>({manuscript_id:id,title:`Paper ${id}`,status:'formatting',invitations:[{invitation_id:id*10,formatter:'Formatter',status:'accepted'}],submissions:[]}))})));
  let goBack; const register=handler=>{goBack=handler;return ()=>{};};
  render(<FormattingPanel role="formatter" token="synthetic" registerManuscriptReturn={register} />);
  fireEvent.click(within((await screen.findByText('#1 Paper 1')).closest('article')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.change(await screen.findByLabelText('Comments'),{target:{value:'Unsaved formatting'}});
  act(()=>{expect(goBack()).toBe(false);});
  expect(screen.getByLabelText('Comments').value).toBe('Unsaved formatting');
  act(()=>{expect(goBack()).toBe(true);});
  expect(screen.getByText('#2 Paper 2')).toBeTruthy();
});

it('never displays an earlier manuscript response after the EIC switches context', async () => {
  let finishFirst;
  vi.stubGlobal('fetch', vi.fn(url => {
    if (url.endsWith('/formatters')) return Promise.resolve({ok:true,json:async()=>[]});
    if (url.endsWith('/manuscripts/1')) return new Promise(resolve => {finishFirst=resolve;});
    if (url.endsWith('/manuscripts/2')) return Promise.resolve({ok:true,json:async()=>({manuscript_id:2,title:'Current paper',status:'formatting',invitations:[],submissions:[]})});
    throw Error('unexpected request');
  }));
  const {rerender}=render(<FormattingPanel role="eic" manuscriptId={1} token="synthetic" canInvite />);
  rerender(<FormattingPanel role="eic" manuscriptId={2} token="synthetic" canInvite />);
  await screen.findByText('Manuscript: formatting');
  await act(async()=>finishFirst({ok:true,json:async()=>({manuscript_id:1,title:'Stale paper',status:'published',invitations:[],submissions:[]})}));
  expect(screen.queryByText(/Stale paper/)).toBeNull();
  expect(screen.getByText('Manuscript: formatting')).toBeTruthy();
  expect(screen.queryByText('Manuscript: published')).toBeNull();
});

it('uses an ID fallback when an assigned formatter manuscript has no title', async () => {
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[{manuscript_id:8,title:' ',status:'formatting',invitations:[{invitation_id:3,formatter:'Formatter',status:'accepted'}],submissions:[]}]})));
  render(<FormattingPanel role="formatter" token="synthetic" />);
  const heading=await screen.findByRole('heading',{name:'Manuscript #8'});
  fireEvent.click(within(heading.closest('article')).getByRole('button',{name:'Open manuscript'}));
  expect(await screen.findByRole('heading',{name:'Manuscript #8'})).toBeTruthy();
});

it('shows staff and personal panels only for an accepted formatter assignment', async () => {
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>String(url).includes('/notes')||String(url).includes('/general-comments')?[]:[{manuscript_id:8,title:'Assigned',status:'formatting',invitations:[{invitation_id:3,formatter:'Formatter',status:'accepted'}],submissions:[]}]})));
  render(<FormattingPanel role="formatter" token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
  expect(screen.getByText('Private Notes')).toBeTruthy();
  expect(screen.getByText('Comments (Staff Shared)')).toBeTruthy();
});

it('does not show personal or staff panels for a pending formatter invitation', async () => {
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[{manuscript_id:8,title:'Invited',status:'formatting',invitations:[{invitation_id:3,formatter:'Formatter',status:'pending'}],submissions:[]}]})));
  render(<FormattingPanel role="formatter" token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
  expect(screen.queryByText('Private Notes')).toBeNull();
  expect(screen.queryByText('Comments (Staff Shared)')).toBeNull();
});

it('preserves formatter note text while collapsed and guards return to the list', async () => {
  vi.stubGlobal('confirm',vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true));
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>String(url).includes('/notes')||String(url).includes('/general-comments')?[]:[{manuscript_id:8,title:'Assigned',status:'formatting',invitations:[{invitation_id:3,formatter:'Formatter',status:'accepted'}],submissions:[]}]})));
  let goBack; const register=handler=>{goBack=handler;return ()=>{};};
  render(<FormattingPanel role="formatter" token="synthetic" registerManuscriptReturn={register} />);
  fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
  const disclosure=screen.getByText('Private Notes');fireEvent.click(disclosure);
  fireEvent.change(screen.getByLabelText('New note'),{target:{value:'Unsaved private note'}});
  fireEvent.click(disclosure);fireEvent.click(disclosure);
  expect(screen.getByLabelText('New note').value).toBe('Unsaved private note');
  act(()=>expect(goBack()).toBe(false));
  expect(screen.getByLabelText('New note').value).toBe('Unsaved private note');
  act(()=>expect(goBack()).toBe(true));
  expect(screen.getByRole('button',{name:'Open manuscript'})).toBeTruthy();
});
it('protects an unsaved personal note when a notification selects another assignment', async () => {
  vi.stubGlobal('confirm',vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true));
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>String(url).includes('/notes')||String(url).includes('/general-comments')?[]:[1,2].map(id=>({manuscript_id:id,title:`Paper ${id}`,status:'formatting',invitations:[{invitation_id:id,formatter:'Formatter',status:'accepted'}],submissions:[]}))})));
  const {rerender}=render(<FormattingPanel role="formatter" token="synthetic" />);
  fireEvent.click(within((await screen.findByText('#1 Paper 1')).closest('article')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByText('Private Notes'));
  fireEvent.change(screen.getByLabelText('New note'),{target:{value:'Unsaved note'}});
  rerender(<FormattingPanel role="formatter" token="synthetic" navigationTarget={{manuscriptId:2}} />);
  expect(screen.getByLabelText('New note').value).toBe('Unsaved note');
  expect(screen.getByRole('heading',{name:'#1 Paper 1'})).toBeTruthy();
  rerender(<FormattingPanel role="formatter" token="synthetic" navigationTarget={{manuscriptId:2}} />);
  expect(await screen.findByRole('heading',{name:'#2 Paper 2'})).toBeTruthy();
});
