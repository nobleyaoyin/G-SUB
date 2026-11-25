import {afterEach, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import useStageProjection, {StageProjectionNotice} from './useStageProjection';
import {matchesWorkflowFilter} from './workflowStatus';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
function Harness({token='one', reviewer=false, items, filter='stage:Proofing'}) {
  const projection = useStageProjection(items, token, filter, reviewer);
  return <><StageProjectionNotice projection={projection}/><output>{projection.items.filter(x=>matchesWorkflowFilter(x,filter)).map(x=>x.manuscript_id).join(',')}</output></>;
}
it('uses authorized progress to distinguish proofing and formatting',async()=>{
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>({manuscript_id:String(url).includes('/1/')?1:2,status:'formatting',current_stage:String(url).includes('/1/')?'Proofing':'Formatting'})})));
  render(<Harness items={[{manuscript_id:1,status:'formatting'},{manuscript_id:2,status:'formatting'}]}/>);
  expect((await screen.findByText('1')).textContent).toBe('1');
});
it('fails closed for denied or stale progress',async()=>{
  vi.stubGlobal('fetch',vi.fn(async url=>String(url).includes('/1/')?{ok:false}:{ok:true,json:async()=>({manuscript_id:2,status:'published',current_stage:'Proofing'})}));
  render(<Harness items={[{manuscript_id:1,status:'formatting'},{manuscript_id:2,status:'formatting'}]}/>);
  expect(await screen.findByText(/stages are unavailable/)).toBeTruthy();
  expect(screen.getByText('',{selector:'output'}).textContent).toBe('');
});
it('does not infer reviewer stage from an assignment or accept denied progress', async () => {
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status:404})));
  render(<Harness reviewer items={[{manuscript_id:7,status:'assigned'}]}/>);
  expect(await screen.findByText(/stages are unavailable/)).toBeTruthy();
  expect(screen.getByText('',{selector:'output'}).textContent).toBe('');
});
it('reports malformed manuscript IDs rather than inferring a stage', async () => {
  vi.stubGlobal('fetch',vi.fn());
  render(<Harness items={[{manuscript_id:'not-an-id',status:'formatting'}]}/>);
  expect(await screen.findByText(/stages are unavailable/)).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});

it('discards an old identity response when the token changes', async () => {
  let finish;
  vi.stubGlobal('fetch',vi.fn((url, options) => options.headers.Authorization === 'Bearer one'
    ? new Promise(resolve => {finish=resolve}) : Promise.resolve({ok:false,status:404})));
  const items=[{manuscript_id:1,status:'formatting'}];
  const {rerender}=render(<Harness token="one" items={items}/>);
  rerender(<Harness token="two" items={items}/>);
  expect(await screen.findByText(/stages are unavailable/)).toBeTruthy();
  await act(async()=>finish({ok:true,json:async()=>({manuscript_id:1,status:'formatting',current_stage:'Proofing'})}));
  expect(screen.getByText('',{selector:'output'}).textContent).toBe('');
});

it('marks proof sub-stage counts unavailable when one authorized response lacks evidence', async () => {
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>({manuscript_id:String(url).includes('/1/')?1:2,status:'formatting',current_stage:'Proofing',formatting_substage:String(url).includes('/1/')?'pending_author':null})})));
  render(<Harness filter="stage:Proofing|status:proof:pending_author" items={[{manuscript_id:1,status:'formatting'},{manuscript_id:2,status:'formatting'}]}/>);
  expect(await screen.findByText(/stages are unavailable/)).toBeTruthy();
  expect(screen.getByText('1',{selector:'output'})).toBeTruthy();
});

it('rechecks stage evidence on window focus and does not retain stale matches', async () => {
  let stage = 'Proofing';
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({manuscript_id:1,status:'formatting',current_stage:stage})})));
  render(<Harness items={[{manuscript_id:1,status:'formatting'}]}/>);
  expect(await screen.findByText('1')).toBeTruthy();
  stage = 'Formatting';
  fireEvent.focus(window);
  await screen.findByText('', {selector:'output'});
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('limits concurrent progress requests and deduplicates manuscript IDs', async () => {
  let running = 0, maximum = 0;
  vi.stubGlobal('fetch', vi.fn(async url => {
    running++; maximum = Math.max(maximum, running);
    await new Promise(resolve => setTimeout(resolve, 5)); running--;
    const id = Number(String(url).match(/manuscripts\/(\d+)\/progress/)[1]);
    return {ok:true,json:async()=>({manuscript_id:id,status:'formatting',current_stage:'Proofing'})};
  }));
  const items=Array.from({length:8},(_,i)=>({manuscript_id:i+1,status:'formatting'}));
  render(<Harness items={[...items,items[0]]}/>);
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(8));
  expect(maximum).toBeLessThanOrEqual(5);
});

it('does not infer a stage when the authorized progress response is unavailable', async () => {
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:1,status:'formatting',current_stage:null,formatting_substage:null})})));
  render(<Harness items={[{manuscript_id:1,status:'formatting'}]}/>);
  expect(await screen.findByText(/stages are unavailable/)).toBeTruthy();
  expect(screen.getByText('',{selector:'output'}).textContent).toBe('');
});

it('limits a 100-manuscript ambiguous list to five concurrent requests', async () => {
  let running = 0, maximum = 0;
  vi.stubGlobal('fetch', vi.fn(async url => {
    running++; maximum = Math.max(maximum, running);
    await new Promise(resolve => setTimeout(resolve, 1)); running--;
    const id = Number(String(url).match(/manuscripts\/(\d+)\/progress/)[1]);
    return {ok:true,json:async()=>({manuscript_id:id,status:'formatting',current_stage:'Proofing'})};
  }));
  render(<Harness items={Array.from({length:100},(_,i)=>({manuscript_id:i+1,status:'formatting'}))}/>);
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(100));
  expect(maximum).toBeLessThanOrEqual(5);
});
