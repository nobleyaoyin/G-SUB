import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import AuthorGenerationHistory from './AuthorGenerationHistory';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
it('separates revisions and approved outputs without revealing internal records',async()=>{
 const entries=[{id:'revision:2',section:'generations',stage:'Revision',title:'Author revision source',review_round:2,status:'Revision source recorded; file integrity unavailable'},{id:'formatting:3',section:'outputs',stage:'Formatting',title:'Approved formatting artifact',status:'Approved',download:{kind:'approved_formatting',id:3}}];
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,entries,unavailable_sources:[],historical_notice:'Historical release status unavailable.'})})));
 render(<AuthorGenerationHistory token="synthetic" manuscriptId={7}/>);fireEvent.click(screen.getByText('Generation history'));
 expect(await screen.findByText(/Author revision source/)).toBeTruthy();expect(screen.getByRole('heading',{name:'Review round 2'})).toBeTruthy();
 expect(screen.getByText('Historical release status unavailable.')).toBeTruthy();expect(screen.getByRole('button',{name:'Download approved document'})).toBeTruthy();expect(screen.queryByText(/Reviewer/)).toBeNull();
});
it('does not show stale data after switching manuscripts',async()=>{
 let release;vi.stubGlobal('fetch',vi.fn(url=>url.includes('/1/')?new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({manuscript_id:1,entries:[{id:'old',section:'outputs',title:'Old secret'}],unavailable_sources:[]})})}):Promise.resolve({ok:true,json:async()=>({manuscript_id:2,entries:[],unavailable_sources:[],historical_notice:'Historical release status unavailable.'})})));
 const {rerender}=render(<AuthorGenerationHistory token="synthetic" manuscriptId={1}/>);fireEvent.click(screen.getByText('Generation history'));rerender(<AuthorGenerationHistory token="synthetic" manuscriptId={2}/>);
 expect(await screen.findByText('Historical release status unavailable.')).toBeTruthy();release();expect(screen.queryByText('Old secret')).toBeNull();
});
it('offers a submitted document download only for a valid snapshot identity',async()=>{
 const entries=[{id:'snapshot',section:'submissions',stage:'Submission',title:'Original submission source',version:1,status:'Submitted; integrity verified on download',download:{kind:'author_submission',id:'a'.repeat(32)}},{id:'bad',section:'submissions',stage:'Submission',title:'Unavailable source',download:{kind:'author_submission',id:'../bad'}}];
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,entries,unavailable_sources:[],historical_notice:'Historical release status unavailable.'})})));
 render(<AuthorGenerationHistory token="synthetic" manuscriptId={7}/>);fireEvent.click(screen.getByText('Generation history'));
 expect(await screen.findAllByRole('button',{name:'Download submitted document'})).toHaveLength(1);
});
it('downloads an approved final edit through the selected manuscript history route',async()=>{
 const entries=[{id:'final:9',section:'outputs',stage:'Final Editing',title:'Approved final editing document',status:'Approved; file integrity unavailable',download:{kind:'approved_final',id:9}}];
 const fetcher=vi.fn(async url=>url.endsWith('/generation-history')?{ok:true,json:async()=>({manuscript_id:7,entries,unavailable_sources:[],historical_notice:'Historical release status unavailable.'})}:{ok:true,blob:async()=>new Blob(['synthetic']),headers:{get:()=> 'application/pdf'}});
 vi.stubGlobal('fetch',fetcher);vi.stubGlobal('URL',{createObjectURL:vi.fn(()=> 'blob:synthetic'),revokeObjectURL:vi.fn()});
 const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
 render(<AuthorGenerationHistory token="synthetic" manuscriptId={7}/>);fireEvent.click(screen.getByText('Generation history'));
 fireEvent.click(await screen.findByRole('button',{name:'Download approved final edit'}));
 await vi.waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url.endsWith('/manuscripts/7/generation-history/final-editing/9/download'))).toBe(true));
 await vi.waitFor(()=>expect(click).toHaveBeenCalled());
 click.mockRestore();
});
it('shows readable recorded times and distinguishes unavailable or timezone-less records',async()=>{
 const entries=[
  {id:'utc',section:'submissions',title:'UTC record',recorded_at:'2026-11-21T10:22:33Z',status:'Recorded'},
  {id:'naive',section:'submissions',title:'Timezone unknown',recorded_at:'2026-11-21T10:22:33',status:'Recorded'},
  {id:'badtime',section:'submissions',title:'Invalid time',recorded_at:'invalid'}
 ];
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,entries,unavailable_sources:[]})})));
 render(<AuthorGenerationHistory token="synthetic" manuscriptId={7}/>);fireEvent.click(screen.getByText('Generation history'));
 expect((await screen.findByText('UTC record')).closest('li').textContent).toContain('(local time)');
 expect(screen.getByText('Timezone unknown').closest('li').textContent).toContain('(timezone unavailable)');
 expect(screen.getByText('Invalid time').closest('li').textContent).toContain('Time unavailable');
 expect(screen.getByText('Invalid time').closest('li').textContent).toContain('Status unavailable');
});
it('shows an accessible error for unavailable history',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:false})));
 render(<AuthorGenerationHistory token="synthetic" manuscriptId={7}/>);fireEvent.click(screen.getByText('Generation history'));
 expect((await screen.findByRole('alert')).textContent).toBe('Generation history unavailable.');
});
it('omits the specific release-history explanation while keeping verified artifacts',async()=>{
 const entries=[{id:'revision',section:'generations',title:'Recorded artifact',review_round:1,status:'Recorded'}];
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,entries,unavailable_sources:[],historical_notice:'Historical release status unavailable. Artifacts with unknown release are not listed.'})})));
 render(<AuthorGenerationHistory token="synthetic" manuscriptId={7}/>);fireEvent.click(screen.getByText('Generation history'));
 expect(await screen.findByText('Recorded artifact')).toBeTruthy();
 expect(screen.queryByText('Historical release status unavailable. Artifacts with unknown release are not listed.')).toBeNull();
});
