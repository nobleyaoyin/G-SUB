import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import ManuscriptProgress from './ManuscriptProgress';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
it('only links the matching Author proof task and clears it on refresh',async()=>{
 let task={task_state:'action_required',task_message:'Review the formatted proof.',relevant_stage:'Formatting',action_label:'View formatting review',permitted_action_target:'#author-formatting-action-1'};
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({manuscript_id:1,current_stage:'Formatting',stages:[],participant_task:task})})));
 const view=render(<ManuscriptProgress manuscriptId={1} token="synthetic"/>);
 expect((await screen.findByRole('link',{name:'View formatting review'})).getAttribute('href')).toBe('#author-formatting-action-1');
 task={...task,permitted_action_target:'#author-formatting-action-2'};view.rerender(<ManuscriptProgress manuscriptId={1} token="synthetic" revision={1}/>);
 await waitFor(()=>expect(screen.queryByRole('link',{name:'View formatting review'})).toBeNull());
 task={task_state:'waiting',task_message:'Waiting for the EIC to review the formatted proof.',relevant_stage:'Formatting',action_label:null,permitted_action_target:null};
 view.rerender(<ManuscriptProgress manuscriptId={1} token="synthetic" revision={2}/>);
 expect(await screen.findByText(/Waiting for the EIC to review/)).toBeTruthy();
 expect(screen.queryByRole('link',{name:'View formatting review'})).toBeNull();
});
