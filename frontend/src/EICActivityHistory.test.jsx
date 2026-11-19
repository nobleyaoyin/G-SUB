import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import EICActivityHistory, {eicActivity} from './EICActivityHistory';
afterEach(cleanup);
const source = {
 manuscript:{manuscript_id:7,created_at:'2025-01-01T00:00:00Z'},
 scans:[{decision:'pass',created_at:'2026-01-01T00:00:00Z',comments:'private screening'}],
 invitations:[],submissions:[{submission_id:2,status:'submitted',editor:'Editor',created_at:'2026-02-01T00:00:00Z'}, {submission_id:2,status:'submitted',editor:'Editor',created_at:'2026-02-01T00:00:00Z'}],
 confirmations:[],assignments:[{assignment_id:1,review_round:2,reviewer:'Secret reviewer',status:'completed',review:{submitted_at:'2026-02-01T00:00:00Z',comments:'Secret review'}}],
 decisions:[{review_round:2,decision:'accept',decided_at:'2026-03-01T00:00:00Z',comments:'Secret decision'}],final_invitations:[],final_submissions:[{submission_id:3,status:'submitted'}],author_agreement:null,
};
it('orders dates newest first with stable ties, deduplicates identified rows and leaves undated last',()=>{
 const events=eicActivity(source);
 expect(events.map(e=>e.key)).toEqual(['decision:0','initial-submission:2','review:1','scan:0','manuscript:7','assignment:1','final-submission:3']);
 expect(JSON.stringify(events)).not.toMatch(/Secret|private screening/);
 expect(eicActivity({...source,decisions:[],assignments:[]}).some(e=>e.key==='decision:0')).toBe(false);
});
it('renders metadata separately from comments and retains document actions',()=>{
 const download=vi.fn();render(<EICActivityHistory overview={source} onDownload={download}/>);
 fireEvent.click(screen.getByText(/Activity History/));
 expect(screen.getByText('Review submitted · Round 2')).toBeTruthy();
 expect(screen.queryByText('Secret review')).toBeNull();
 expect(screen.getAllByText('Date unavailable').length).toBe(2);
 fireEvent.click(screen.getByRole('button',{name:'Download initial editing document'}));
 expect(download).toHaveBeenCalledWith('/eic/initial-editing/submissions/2/download');
});
it('shows only recorded invitation responses in chronological order without comment text',()=>{
 const events=eicActivity({...source,invitations:[{invitation_id:4,status:'accepted',invited_at:'2026-03-02T00:00:00Z',responded_at:'2026-03-03T00:00:00Z',comments:'Private comment'},{invitation_id:5,status:'pending',responded_at:null}],final_invitations:[{invitation_id:8,status:'declined',invited_at:'2026-04-01T00:00:00Z',responded_at:'2026-04-02T00:00:00Z'}]});
 expect(events.slice(0,4).map(e=>e.key)).toEqual(['final-response:8','final-invitation:8','initial-response:4','initial-invitation:4']);
 expect(events.some(e=>e.key==='initial-response:5')).toBe(false);
 expect(JSON.stringify(events)).not.toContain('Private comment');
});
it('uses only matching formatting records and never exposes comments',()=>{
 const formatting={manuscript_id:7,submissions:[{submission_id:9,status:'pending_author',created_at:'2026-05-01T00:00:00Z',comments:'private formatting'}],publication:{submission_id:9,published_at:'2026-06-01T00:00:00Z'}};
 const events=eicActivity(source,formatting);
 expect(events[0].key).toBe('publication:9');
 expect(events[1].key).toBe('formatting-submission:9');
 expect(JSON.stringify(events)).not.toContain('private formatting');
 expect(eicActivity(source,{...formatting,manuscript_id:8}).some(e=>e.key==='publication:9')).toBe(false);
 expect(eicActivity(source,{...formatting,publication:{submission_id:9}}).some(e=>e.key==='publication:9')).toBe(false);
});
it('shows recorded distribution and revocation events without implying email or download',()=>{
 const history=[{grant_id:'synthetic-grant',version:2,invitation_kind:'final',invitation_id:4,created_at:'2026-07-01T00:00:00Z',revoked_at:'2026-07-02T00:00:00Z',email:'not_requested'}];
 const events=eicActivity(source,null,history);
 expect(events.slice(0,2).map(e=>e.key)).toEqual(['revocation:synthetic-grant','distribution:synthetic-grant']);
 expect(JSON.stringify(events)).not.toMatch(/email sent|downloaded/i);
 expect(eicActivity(source,null,[{grant_id:'old',status:'revoked'}]).some(e=>e.key.includes('old'))).toBe(false);
});
