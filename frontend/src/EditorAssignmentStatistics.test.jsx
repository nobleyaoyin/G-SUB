import {afterEach, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen, within} from '@testing-library/react';
import EditorAssignmentStatistics from './EditorAssignmentStatistics';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
it('starts collapsed and retains all detailed statistics behind a separate disclosure',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[]})));
 render(<EditorAssignmentStatistics token="synthetic" userId={1} revision={0} summary={{total_manuscripts:3,not_assigned:1}}/>);
 const outer=screen.getByText('Statistics').closest('details');
 expect(outer.open).toBe(false);
 fireEvent.click(screen.getByText('Statistics'));
 expect((await screen.findByText('Initial assigned')).parentElement.textContent).toContain('0');
 expect(within(screen.getByLabelText('Assignment summary')).getByText('Total manuscripts').parentElement.textContent).toContain('3');
 const detail=screen.getByText('Detailed statistics').closest('details');
 expect(detail.open).toBe(false);
 fireEvent.click(screen.getByText('Detailed statistics'));
 expect(within(screen.getByRole('region',{name:'General editor workload statistics'})).getByText('Not assigned').parentElement.textContent).toContain('1');
});
it('shows separately derived assignments without counting another editor’s final edit',async()=>{
 const initial=[{manuscript_id:1,invitation:{status:'accepted'},submissions:[{status:'pending_author'}]}];
 const final=[{manuscript_id:2,invitation_id:8,status:'accepted',submissions:[{invitation_id:8,editor_id:2,status:'author_approved'}]}];
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>String(url).includes('initial-editing')?initial:final})));
 render(<EditorAssignmentStatistics token="synthetic" userId={1} revision={0}/>);
 fireEvent.click(screen.getByText('Statistics'));
 fireEvent.click(screen.getByText('Detailed statistics'));
 const a=await screen.findByRole('region',{name:'Initial editing statistics'});
 const b=screen.getByRole('region',{name:'Final editing statistics'});
 expect(within(a).getByText('Submitted for review').parentElement.textContent).toContain('1');
 expect(within(b).getByText('Completed assignments').parentElement.textContent).toContain('0');
 expect(within(b).getByText('Status unavailable').parentElement.textContent).toContain('1');
});
it('shows unavailable separately from an empty authorized list',async()=>{
 vi.stubGlobal('fetch',vi.fn(async url=>String(url).includes('initial-editing')?{ok:false}:{ok:true,json:async()=>[]}));
 render(<EditorAssignmentStatistics token="synthetic" userId={1} revision={0}/>);
 fireEvent.click(screen.getByText('Statistics'));
 fireEvent.click(screen.getByText('Detailed statistics'));
 expect(await screen.findByText('Assignment statistics are unavailable.')).toBeTruthy();
 expect(within(screen.getByRole('region',{name:'Final editing statistics'})).getByText('Assigned manuscripts').parentElement.textContent).toContain('0');
});

it('does not reuse assignment counts after the signed-in editor changes',async()=>{
 const deferred=[];
 vi.stubGlobal('fetch',vi.fn((url, options)=>options.headers.Authorization==='Bearer first'
   ? new Promise(resolve=>deferred.push(resolve)) : Promise.resolve({ok:true,json:async()=>[]})));
 const {rerender}=render(<EditorAssignmentStatistics token="first" userId={1} revision={0}/>);
 fireEvent.click(screen.getByText('Statistics'));
 fireEvent.click(screen.getByText('Detailed statistics'));
 rerender(<EditorAssignmentStatistics token="second" userId={2} revision={0}/>);
 const initial=await screen.findByRole('region',{name:'Initial editing statistics'});
 expect(within(initial).getByText('Assigned manuscripts').parentElement.textContent).toContain('0');
 await act(async()=>deferred.forEach(resolve=>resolve({ok:true,json:async()=>[{manuscript_id:7,invitation:{status:'accepted'},submissions:[]}]})));
 expect(within(initial).getByText('Assigned manuscripts').parentElement.textContent).toContain('0');
});

it('keeps the distinct combined status breakdown inside the same panel and handles unavailable data', async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[]})));
 const {rerender}=render(<EditorAssignmentStatistics token="synthetic" userId={1} revision={0} statusItems={[{status:'revision_required'},{status:'formatting'}]} />);
 fireEvent.click(screen.getByText('Statistics'));
 fireEvent.click(screen.getByText('Detailed statistics'));
 const region=screen.getByRole('region',{name:'Combined editor and formatting manuscript status'});
 expect(region.closest('details')).toBeTruthy();
 expect(within(region).getByText('Revision required').parentElement.textContent).toContain('1');
 expect(within(region).getByText('Formatting').parentElement.textContent).toContain('1');
 rerender(<EditorAssignmentStatistics token="synthetic" userId={1} revision={0} statusItems={[]} statusError="failed" />);
 expect(within(region).getByText('Status breakdown is unavailable.')).toBeTruthy();
});
