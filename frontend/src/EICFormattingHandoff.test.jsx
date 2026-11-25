import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import {EICFormattingWorkspace} from './EICStageContent';

vi.mock('./FormattingPanel',()=>({default:({canInvite})=><p>{canInvite?'Invitation eligible':'Invitation unavailable'}</p>}));
afterEach(cleanup);

it('opens the existing Formatting workspace for an approved final-edit handoff only',()=>{
 const props={currentStage:'Final Editing',selectedStage:'Formatting',selected:4,token:'synthetic',refresh:vi.fn()};
 const {container,rerender}=render(<EICFormattingWorkspace {...props} latestFinal={{status:'pending_author'}}/>);
 expect(container.firstChild.hidden).toBe(true);
 rerender(<EICFormattingWorkspace {...props} latestFinal={{status:'author_approved'}}/>);
 expect(container.firstChild.hidden).toBe(false);
 expect(screen.getByText('Invitation eligible')).toBeTruthy();
 rerender(<EICFormattingWorkspace {...props} selectedStage="Final Editing" latestFinal={{status:'author_approved'}}/>);
 expect(container.firstChild.hidden).toBe(true);
 rerender(<EICFormattingWorkspace {...props} currentStage="Formatting" latestFinal={{status:'author_approved'}}/>);
 expect(container.firstChild.hidden).toBe(false);
});
