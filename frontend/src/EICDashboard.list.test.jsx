import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, within} from '@testing-library/react';
import EICDashboard from './EICDashboard';
import {prepareManuscriptList, UNKNOWN_STATUS} from './eicManuscriptList';

vi.mock('./NotificationBell',()=>({default:()=>null}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

it('sorts deterministically in both directions and keeps missing values last',()=>{
  const items=[{manuscript_id:2,title:'Alpha',status:'submitted',created_at:'2026-02-01'}, {manuscript_id:1,title:'Alpha',status:'submitted',created_at:'2026-01-01'}, {manuscript_id:3,title:'Zulu',status:null,created_at:null}];
  const ids=(field,dir)=>prepareManuscriptList(items,'','',field,dir).filtered.map(x=>x.manuscript_id);
  expect(ids('title','asc')).toEqual([1,2,3]);
  expect(ids('title','desc')).toEqual([3,1,2]);
  expect(ids('created_at','asc')).toEqual([1,2,3]);
  expect(ids('created_at','desc')).toEqual([2,1,3]);
  expect(ids('status','asc')).toEqual([1,2,3]);
  expect(ids('status','desc')).toEqual([1,2,3]);
  expect(prepareManuscriptList(items,'','', 'id','asc').counts.get(UNKNOWN_STATUS)).toBe(1);
});

it('combines search, status, counts, deterministic ordering and pagination',async()=>{
  const items=Array.from({length:23},(_,i)=>({manuscript_id:i+1,title:`Paper ${String(i+1).padStart(2,'0')}`,status:i%2?'revised':'submitted',created_at:'2026-01-01T00:00:00Z'}));
  vi.stubGlobal('fetch',vi.fn(async url=>url.endsWith('/manuscripts/')?{ok:true,json:async()=>[...items,items[0]]}:url.endsWith('/eic/editors')?{ok:true,json:async()=>[]}:{ok:false,json:async()=>({})}));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  expect((await screen.findByText(/Accessible manuscripts:/)).textContent).toContain('23');
  expect(screen.getByText(/Matching results:/).textContent).toContain('23');
  const counts=screen.getByRole('list',{name:'Accessible manuscripts by status'});
  expect(counts.textContent).toContain('submitted: 12');
  expect(counts.textContent).toContain('revised: 11');
  expect(screen.getByText('Page 1 of 3 · 23 results')).toBeTruthy();
  expect(screen.getByRole('button',{name:'Previous'}).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(screen.getByText('Page 2 of 3 · 23 results')).toBeTruthy();
  expect(screen.queryByRole('button',{name:'#1 Paper 01'})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(screen.getByText('Page 3 of 3 · 23 results')).toBeTruthy();
  expect(screen.getByRole('button',{name:'Next'}).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Sort by'),{target:{value:'title'}});
  fireEvent.click(screen.getByRole('button',{name:/Order: Ascending/}));
  const table=screen.getByRole('table');
  expect(within(table).getAllByRole('row')[1].textContent).toContain('Paper 23');
  fireEvent.change(screen.getByLabelText('Status'),{target:{value:'revised'}});
  expect(screen.getByText('Page 1 of 2 · 11 results')).toBeTruthy();
  expect(screen.getByRole('button',{name:/Order: Descending/})).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Search'),{target:{value:'12'}});
  expect(screen.getByText('Page 1 of 1 · 1 results')).toBeTruthy();
  expect(screen.getByRole('button',{name:'#12 Paper 12'})).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Search'),{target:{value:'Paper 12'}});
  expect(screen.getByText('Page 1 of 1 · 1 results')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Search'),{target:{value:'No match'}});
  expect(screen.getByText('No manuscripts match the current search and filters.')).toBeTruthy();
  expect(screen.getByText('Page 0 of 0 · 0 results')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Search'),{target:{value:''}});
  fireEvent.change(screen.getByLabelText('Status'),{target:{value:''}});
  expect(screen.getByText('Page 1 of 3 · 23 results')).toBeTruthy();
});

it('shows failure and retry without a misleading zero summary',async()=>{
  let fail=true;
  vi.stubGlobal('fetch',vi.fn(async url=>url.endsWith('/manuscripts/')&&fail?{ok:false,json:async()=>({detail:'Synthetic failure'})}:{ok:true,json:async()=>[]}));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  expect(await screen.findByText('Unable to load the manuscript list.')).toBeTruthy();
  expect(screen.queryByText(/Accessible manuscripts:/)).toBeNull();
  fail=false;fireEvent.click(screen.getByRole('button',{name:'Retry manuscript list'}));
  expect(await screen.findByText('No accessible manuscripts are available.')).toBeTruthy();
});

it('changes page size and clears a case-insensitive search',async()=>{
  const items=Array.from({length:27},(_,i)=>({manuscript_id:i+1,title:`Paper ${i+1}`,status:'submitted'}));
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/manuscripts/')?items:[]})));
  render(<EICDashboard user={{name:'Synthetic'}} token="synthetic" />);
  expect(await screen.findByText('Page 1 of 3 · 27 results')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Rows per page'),{target:{value:'25'}});
  expect(screen.getByText('Page 1 of 2 · 27 results')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Next'}));
  expect(screen.getByText('Page 2 of 2 · 27 results')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Search'),{target:{value:'pApEr 2'}});
  expect(screen.getByText('Page 1 of 1 · 9 results')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Clear search'}));
  expect(screen.getByText('Page 1 of 2 · 27 results')).toBeTruthy();
});
