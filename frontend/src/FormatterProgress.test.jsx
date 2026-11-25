import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
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
it('omits only redundant embedded editor progress while retaining formatting actions', async () => {
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/progress')
    ? {manuscript_id:8,review_round:2,current_stage:'Formatting',stages:[{name:'Formatting',state:'current'}]}
    : [{manuscript_id:8,title:'Synthetic',status:'formatting',invitations:[{invitation_id:5,formatter:'Synthetic',status:'accepted'}],submissions:[]}]})));
  const {rerender} = render(<FormattingPanel role="editor" manuscriptId={8} token="synthetic" />);
  expect(await screen.findByRole('list',{name:'Workflow timeline'})).toBeTruthy();
  expect(screen.getByRole('button',{name:'Download approved final edit'})).toBeTruthy();
  rerender(<FormattingPanel role="editor" manuscriptId={8} token="synthetic" showProgress={false} />);
  expect(screen.queryByRole('list',{name:'Workflow timeline'})).toBeNull();
  expect(screen.getByRole('button',{name:'Download approved final edit'})).toBeTruthy();
});

it('uses a current authorized formatting task as its single primary prompt', async () => {
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/progress')
    ? {manuscript_id:8,review_round:1,current_stage:'Formatting',stages:[],participant_task:{task_state:'waiting',task_message:'Waiting for the formatted proof to be reviewed.',relevant_stage:'Formatting'}}
    : [{manuscript_id:8,title:'Synthetic',status:'formatting',invitations:[{invitation_id:5,formatter:'Synthetic',status:'accepted'}],submissions:[]}]})));
  render(<FormattingPanel role="formatter" token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
  expect(await screen.findByText(/Waiting for the formatted proof to be reviewed/)).toBeTruthy();
  expect(screen.getAllByText('Next action:')).toHaveLength(1);
});

it('links the current authorized formatting task to its local actions', async () => {
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/progress')
    ? {manuscript_id:8,current_stage:'Formatting',stages:[],participant_task:{task_state:'action_required',task_message:'Prepare a proof.',relevant_stage:'Formatting',action_label:'View formatting actions',permitted_action_target:'#formatting-action-8'}}
    : [{manuscript_id:8,title:'Synthetic',status:'formatting',invitations:[{invitation_id:5,formatter:'Synthetic',status:'accepted'}],submissions:[]}]})));
  render(<FormattingPanel role="formatter" token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
  expect((await screen.findByRole('link',{name:'View formatting actions'})).getAttribute('href')).toBe('#formatting-action-8');
});

it('does not show an obsolete formatting task after changing manuscripts', async () => {
  let finishFirst;
  const items=[1,2].map(id=>({manuscript_id:id,title:`Paper ${id}`,status:'formatting',invitations:[{invitation_id:id,formatter:'Synthetic',status:'accepted'}],submissions:[]}));
  vi.stubGlobal('fetch',vi.fn(url=>{
    if(url.endsWith('/manuscripts/1/progress')) return new Promise(resolve=>{finishFirst=resolve;});
    if(url.endsWith('/manuscripts/2/progress')) return Promise.resolve({ok:true,json:async()=>({manuscript_id:2,current_stage:'Formatting',stages:[],participant_task:{task_state:'waiting',task_message:'Current second task.',relevant_stage:'Formatting'}})});
    return Promise.resolve({ok:true,json:async()=>items});
  }));
  render(<FormattingPanel role="formatter" token="synthetic" />);
  fireEvent.click(within((await screen.findByText('#1 Paper 1')).closest('article')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
  fireEvent.click(within(screen.getByText('#2 Paper 2').closest('article')).getByRole('button',{name:'Open manuscript'}));
  expect(await screen.findByText(/Current second task/)).toBeTruthy();
  await act(async()=>finishFirst({ok:true,json:async()=>({manuscript_id:1,current_stage:'Formatting',stages:[],participant_task:{task_state:'waiting',task_message:'Obsolete first task.',relevant_stage:'Formatting'}})}));
  expect(screen.queryByText(/Obsolete first task/)).toBeNull();
});
