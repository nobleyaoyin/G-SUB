import {afterEach, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen} from '@testing-library/react';
import FormattingPanel from './FormattingPanel';
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

for (const outcome of ['success','failure']) {
  it(`does not show an obsolete formatter action ${outcome} after switching manuscripts`, async () => {
    let finish;
    const items=[1,2].map(id=>({manuscript_id:id,title:`Paper ${id}`,status:'formatting',invitations:[{invitation_id:id,status:'pending'}],submissions:[]}));
    vi.stubGlobal('fetch',vi.fn((url,options={})=>options.method==='POST'
      ? new Promise(resolve=>{finish=resolve;})
      : Promise.resolve({ok:true,json:async()=>items})));
    render(<FormattingPanel role="formatter" token="synthetic" />);
    fireEvent.click((await screen.findAllByRole('button',{name:'Open manuscript'}))[0]);
    fireEvent.click(screen.getByRole('button',{name:'Accept formatting invitation'}));
    fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
    fireEvent.click(screen.getAllByRole('button',{name:'Open manuscript'})[1]);
    expect(screen.getByRole('heading',{name:'Paper 2'})).toBeTruthy();
    await act(async()=>finish({ok:outcome==='success',status:outcome==='success'?200:422,json:async()=>outcome==='success'?{}:{detail:'Obsolete A failure'}}));
    expect(screen.queryByText(/Obsolete A failure/)).toBeNull();
    expect(screen.queryByText('Action completed.')).toBeNull();
    expect(screen.getByRole('heading',{name:'Paper 2'})).toBeTruthy();
  });
}

it('keeps documents and submitted review comments bound to their assignment across rounds', async () => {
  const {default:ReviewerDashboard}=await import('./ReviewerDashboard');
  const headers=new Headers({'content-type':'application/json'}); let finishDownload,finishReview,postBody;
  const assignments=[1,2].map(round=>({assignment_id:round,manuscript_id:7,review_round:round,status:'assigned',invitation_status:'accepted',review_file_available:true}));
  const pdfHeaders=new Headers({'content-type':'application/pdf'}); const roundTwoBytes=new Blob(['round 2']);
  vi.stubGlobal('confirm',vi.fn(()=>true));
  vi.stubGlobal('fetch',vi.fn((url,options={})=>{
    if(url.endsWith('/assignments/my')) return Promise.resolve({ok:true,headers,json:async()=>assignments});
    if(url.endsWith('/assignments/1/download')) return new Promise(resolve=>{finishDownload=resolve;});
    if(url.endsWith('/assignments/2/download')) return Promise.resolve({ok:true,headers:pdfHeaders,blob:async()=>roundTwoBytes});
    if(url.endsWith('/reviews/') && options.method==='POST') {postBody=JSON.parse(options.body);return new Promise(resolve=>{finishReview=resolve;});}
    return Promise.resolve({ok:true,headers,json:async()=>({manuscript_id:7,stages:[]})});
  }));
  const create=vi.fn(()=> 'blob:round2');vi.stubGlobal('URL',{createObjectURL:create,revokeObjectURL:vi.fn()});
  const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
  render(<ReviewerDashboard user={{user_id:2,name:'Synthetic'}} token="synthetic" />);
  fireEvent.click((await screen.findAllByRole('button',{name:'Open manuscript'}))[0]);
  expect(screen.getByRole('heading',{name:'Review documents · Round 1'})).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Download Review File'}));
  fireEvent.change(screen.getByLabelText('Review Comments'),{target:{value:'Round one comment'}});
  fireEvent.change(screen.getByLabelText('Recommendation'),{target:{value:'accept'}});
  fireEvent.click(screen.getByRole('button',{name:'Submit Review'}));
  expect(postBody.assignment_id).toBe(1);expect(postBody.comments).toBe('Round one comment');
  fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
  fireEvent.click(screen.getAllByRole('button',{name:'Open manuscript'})[1]);
  expect(screen.getByRole('heading',{name:'Review documents · Round 2'})).toBeTruthy();
  expect(screen.getByLabelText('Review Comments').value).toBe('');
  await act(async()=>finishDownload({ok:true,headers:pdfHeaders,blob:async()=>new Blob(['round 1'])}));
  await act(async()=>finishReview({ok:true,headers,json:async()=>({})}));
  expect(create).not.toHaveBeenCalled(); expect(screen.queryByText(/Review submitted successfully for Assignment #1/)).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Download Review File'}));
  await act(async()=>{});expect(create).toHaveBeenCalledTimes(1);expect(create.mock.calls[0][0]).toBe(roundTwoBytes);
  fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
  fireEvent.click(screen.getAllByRole('button',{name:'Open manuscript'})[0]);
  expect(screen.getByRole('heading',{name:'Review documents · Round 1'})).toBeTruthy();
  expect(screen.getByLabelText('Review Comments').value).toBe('');
  fireEvent.click(screen.getByRole('button',{name:'Download Review File'}));
  const roundOneBytes=new Blob(['round 1']);
  await act(async()=>finishDownload({ok:true,headers:pdfHeaders,blob:async()=>roundOneBytes}));
  expect(create).toHaveBeenCalledTimes(2);
  expect(create.mock.calls[1][0]).toBe(roundOneBytes);
  click.mockRestore();
});

it('ignores a previous account formatter load error and a download after unmount', async () => {
  let rejectOld, finishDownload;
  const items=[{manuscript_id:2,title:'Current account',status:'formatting',invitations:[{invitation_id:2,status:'accepted'}],submissions:[]}];
  vi.stubGlobal('fetch',vi.fn((url,options={})=>{
    if(String(url).includes('/invitations/2/input')) return new Promise(resolve=>{finishDownload=resolve;});
    if(options.headers?.Authorization==='Bearer old') return new Promise((resolve,reject)=>{rejectOld=reject;});
    return Promise.resolve({ok:true,json:async()=>String(url).endsWith('/progress')?{manuscript_id:2,stages:[]}:items});
  }));
  const create=vi.fn();vi.stubGlobal('URL',{createObjectURL:create,revokeObjectURL:vi.fn()});
  const view=render(<FormattingPanel role="formatter" token="old" />);
  view.rerender(<FormattingPanel role="formatter" token="new" />);
  fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
  await act(async()=>rejectOld(new Error('Old account failure')));
  expect(screen.queryByText('Old account failure')).toBeNull();
  expect(screen.getByRole('heading',{name:'Current account'})).toBeTruthy();
  fireEvent.click(await screen.findByRole('button',{name:'Download approved final edit'}));
  view.unmount();
  await act(async()=>finishDownload({ok:true,headers:new Headers(),blob:async()=>new Blob(['old'])}));
  expect(create).not.toHaveBeenCalled();
});
