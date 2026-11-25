import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import ReviewerDashboard from './ReviewerDashboard';
vi.mock('./NotificationBell', () => ({default: () => null}));
vi.mock('./ReviewerProfilePanel', () => ({default: () => null}));
afterEach(() => {cleanup();vi.unstubAllGlobals();});
const headers = new Headers({'content-type':'application/json'});
const ok = value => ({ok:true,headers,json:async()=>value});
it('shows only the completed assignment own review and keeps pending free of invented history', async () => {
 const calls=[];
 vi.stubGlobal('fetch',vi.fn(async url=>{
  calls.push(String(url));
  if(url.endsWith('/assignments/my')) return ok([{assignment_id:1,manuscript_id:9,review_round:1,status:'completed',invitation_status:'accepted'}, {assignment_id:2,manuscript_id:8,review_round:1,status:'assigned',invitation_status:'accepted'}]);
  if(url.includes('/reviews/my/')) return ok({assignment_id:1,manuscript_id:9,review_round:1,comments:'My private review',recommendation:'revision',submitted_at:'2026-01-01T00:00:00Z'});
  if(url.endsWith('/progress'))return ok({manuscript_id:9,review_round:1,stages:[]});
  return ok({});
 }));
 render(<ReviewerDashboard user={{user_id:3,name:'Synthetic'}} token="synthetic" />);
 fireEvent.click(within((await screen.findByText('Manuscript #9')).closest('.reviewer-card')).getByRole('button',{name:'Open manuscript'}));
 const section=await screen.findByRole('region',{name:'Review History'});
 expect(await within(section).findByText('My private review')).toBeTruthy();
 expect(within(section).getByText('revision')).toBeTruthy();
 expect(calls.some(x=>x.endsWith('/reviews/my/manuscripts/9/rounds/1/assignments/1'))).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'Back to manuscripts'}));
 fireEvent.click(within(screen.getByText('Manuscript #8').closest('.reviewer-card')).getByRole('button',{name:'Open manuscript'}));
 expect(screen.queryByRole('region',{name:'Review History'})).toBeNull();
 expect(calls.some(x=>x.includes('/reviews/my/manuscripts/8/'))).toBe(false);
});
it('shows unavailable rather than a mismatched review', async () => {
 vi.stubGlobal('fetch',vi.fn(async url=>url.endsWith('/assignments/my')?ok([{assignment_id:1,manuscript_id:9,review_round:1,status:'completed',invitation_status:'accepted'}]):url.includes('/reviews/my/')?ok({assignment_id:2,manuscript_id:9,review_round:1,comments:'Other private review',recommendation:'accept',submitted_at:'2026-01-01T00:00:00Z'}):ok({manuscript_id:9,stages:[]})));
 render(<ReviewerDashboard user={{user_id:3,name:'Synthetic'}} token="synthetic" />);
 fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
 expect(await screen.findByText('Submitted review is unavailable.')).toBeTruthy();
 expect(screen.queryByText('Other private review')).toBeNull();
});
