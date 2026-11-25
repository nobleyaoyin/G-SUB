import {expect, it} from 'vitest';
import {assignmentStatistics} from './assignmentStatistics';
it('counts initial assignments in mutually exclusive evidence-based categories',()=>{
 const records=[
  {manuscript_id:1,invitation:{status:'pending'},submissions:[]},
  {manuscript_id:2,invitation:{status:'accepted'},submissions:[]},
  {manuscript_id:3,invitation:{status:'accepted'},submissions:[{status:'pending_author'}]},
  {manuscript_id:4,invitation:{status:'accepted'},submissions:[{status:'eic_approved',confirmation:'confirm'}]},
  {manuscript_id:5,invitation:{status:'accepted'},submissions:[{status:'unknown'}]},
 ];
 expect(assignmentStatistics(records,'initial',1)).toEqual({assigned:5,invitation:1,work:1,submitted:1,completed:1,unknown:1});
 expect(assignmentStatistics([records[0],records[0]],'initial',1)).toBeNull();
});
it('counts only submissions bound to the editor and the final invitation',()=>{
 const records=[{manuscript_id:1,invitation_id:9,status:'accepted',submissions:[{invitation_id:8,editor_id:2,status:'author_approved'}]},
 {manuscript_id:2,invitation_id:10,status:'accepted',submissions:[{invitation_id:10,editor_id:1,status:'author_approved'}]}];
 expect(assignmentStatistics(records,'final',1)).toEqual({assigned:2,invitation:0,work:1,submitted:0,completed:1,unknown:0});
 expect(assignmentStatistics(records,'final',undefined)).toBeNull();
 expect(assignmentStatistics([], 'final', 1).assigned).toBe(0);
 expect(assignmentStatistics([{manuscript_id:3,status:'unexpected'}], 'final', 1)).toBeNull();
});
