import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import AuthorGenerationHistory from './AuthorGenerationHistory';

afterEach(()=>{cleanup();vi.unstubAllGlobals()});
it('shows recorded format and keeps legacy or unrecognized formats unavailable',async()=>{
 const entries=[
  {id:'source',section:'submissions',stage:'Submission',title:'Recorded source',file_format:'txt'},
  {id:'legacy',section:'submissions',stage:'Submission',title:'Legacy source'},
  {id:'unsafe',section:'submissions',stage:'Submission',title:'Unrecognized source',file_format:'private-name.exe'}
 ];
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:7,entries,unavailable_sources:[]})})));
 render(<AuthorGenerationHistory token="synthetic" manuscriptId={7}/>);
 fireEvent.click(screen.getByText('Generation history'));
 expect((await screen.findByText('Recorded source')).closest('li').textContent).toContain('Format TXT');
 expect(screen.getByText('Legacy source').closest('li').textContent).toContain('Format unavailable');
 expect(screen.getByText('Unrecognized source').closest('li').textContent).toContain('Format unavailable');
 expect(screen.queryByText(/private-name\.exe/)).toBeNull();
});
