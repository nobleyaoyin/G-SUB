import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import NotificationBell from './NotificationBell';
import userEvent from '@testing-library/user-event';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('shows unread notice, marks it read and opens its manuscript', async()=>{
  let read=false;const navigate=vi.fn();
  const request=vi.fn(async (url, options={})=>{
    if(options.method==='PATCH') {read=true;return {ok:true,json:async()=>({})};}
    return {ok:true,json:async()=>url.endsWith('/unread-count')?{unread_count:read?0:1}:[{notification_id:7,manuscript_id:4,message:'Synthetic notice',created_at:'2026-01-01T00:00:00Z',is_read:read}]};
  });
  vi.stubGlobal('fetch',request);render(<NotificationBell token="synthetic" onNavigate={navigate} />);
  fireEvent.click(screen.getByRole('button',{name:'Notifications'}));
  fireEvent.click(await screen.findByRole('button',{name:'Mark as read'}));
  await waitFor(()=>expect(screen.queryByRole('button',{name:'Mark as read'})).toBeNull());
  fireEvent.click(screen.getByRole('button',{name:'Synthetic notice'}));
  expect(navigate).toHaveBeenCalledWith(expect.objectContaining({manuscript_id:4}));
  expect(screen.queryByRole('button',{name:/refresh|reload|sync/i})).toBeNull();
});

it.each([[0,null],[1,'1'],[42,'42'],[132,'99+']])('shows unread count %s without obscuring the icon', async(count, visible)=>{
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/unread-count')?{unread_count:count}:[]})));
  render(<NotificationBell token="synthetic" />);
  const button=screen.getByRole('button',{name:'Notifications'});
  expect(button.querySelector('svg.notification-icon')).toBeTruthy();
  await waitFor(()=>expect(button.querySelector('.notification-badge')?.textContent ?? null).toBe(visible));
  await waitFor(()=>expect(button.getAttribute('aria-describedby')).toBeTruthy());
  if (!count) expect(document.getElementById(button.getAttribute('aria-describedby')).textContent).toBe('No unread notifications');
});

it('opens and closes by keyboard and navigates without marking read', async()=>{
  const navigate=vi.fn();
  const request=vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/unread-count')?{unread_count:1}:[{notification_id:8,manuscript_id:4,message:'Unread notice',created_at:'2026-01-01T00:00:00Z',is_read:false}]}));
  vi.stubGlobal('fetch',request);
  const user=userEvent.setup(); render(<NotificationBell token="synthetic" onNavigate={navigate} />);
  const bell=screen.getByRole('button',{name:'Notifications'});
  await user.tab(); expect(document.activeElement).toBe(bell);
  await user.keyboard('{Enter}');
  expect(await screen.findByRole('button',{name:'Unread notice'})).toBeTruthy();
  await user.click(screen.getByRole('button',{name:'Unread notice'}));
  expect(navigate).toHaveBeenCalledWith(expect.objectContaining({manuscript_id:4}));
  expect(request.mock.calls.some(([,options])=>options?.method==='PATCH')).toBe(false);
  expect(bell.getAttribute('aria-expanded')).toBe('false');
  await user.click(bell); expect(await screen.findByRole('button',{name:'Unread notice'})).toBeTruthy();
  await user.click(bell); expect(screen.queryByRole('button',{name:'Unread notice'})).toBeNull();
});

it('shows an API error without inventing an unread count', async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,json:async()=>({detail:'Synthetic failure'})})));
  render(<NotificationBell token="synthetic" />);
  fireEvent.click(screen.getByRole('button',{name:'Notifications'}));
  expect(await screen.findByText('Synthetic failure')).toBeTruthy();
  expect(document.querySelector('.notification-badge')).toBeNull();
});

it('reports only validated user-specific unread summaries and fails closed on an invalid count', async()=>{
  const summary=vi.fn(); let invalid=false;
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/unread-count')?{unread_count:invalid?-1:2}:[]})));
  render(<NotificationBell token="synthetic" onUnreadSummary={summary} />);
  await waitFor(()=>expect(summary).toHaveBeenLastCalledWith({token:'synthetic',state:'ready',count:2,recent:[]}));
  invalid=true; fireEvent.click(screen.getByRole('button',{name:'Notifications'}));
  await waitFor(()=>expect(summary).toHaveBeenLastCalledWith({token:'synthetic',state:'error',count:null,recent:[]}));
});

it('publishes only the three most recent user notifications and updates read state', async()=>{
  const summary=vi.fn(); let read=false;
  const items=[1,2,3,4].map(id=>({notification_id:id,manuscript_id:id,message:`Notice ${id}`,created_at:'2026-01-01T00:00:00Z',is_read:false}));
  vi.stubGlobal('fetch',vi.fn(async (url,options={})=>{
    if(options.method==='PATCH') read=true;
    return {ok:true,json:async()=>options.method==='PATCH'?{}:url.endsWith('/unread-count')?{unread_count:read?3:4}:items.map((item,i)=>({...item,is_read:read&&i===0}))};
  }));
  render(<NotificationBell token="synthetic" onUnreadSummary={summary} onNavigate={()=>{}} />);
  await waitFor(()=>expect(summary).toHaveBeenLastCalledWith(expect.objectContaining({count:4,recent:items.slice(0,3)})));
  fireEvent.click(screen.getByRole('button',{name:'Notifications'}));
  const buttons=await screen.findAllByRole('button',{name:'Mark as read'});fireEvent.click(buttons[0]);
  await waitFor(()=>expect(summary).toHaveBeenLastCalledWith(expect.objectContaining({count:3,recent:expect.arrayContaining([expect.objectContaining({notification_id:1,is_read:true})])})));
});

it('discards a delayed previous-token response after switching users', async()=>{
  let finishOld;
  const request=vi.fn((url,options)=>{
    const token=options.headers.Authorization;
    if(token==='Bearer first') return new Promise(resolve=>{ (finishOld ||= []).push(()=>resolve({ok:true,json:async()=>url.endsWith('/unread-count')?{unread_count:7}:[{notification_id:1,manuscript_id:1,message:'Old private notice',created_at:'2026-01-01T00:00:00Z',is_read:false}]})); });
    return Promise.resolve({ok:true,json:async()=>url.endsWith('/unread-count')?{unread_count:1}:[{notification_id:2,manuscript_id:2,message:'New notice',created_at:'2026-01-01T00:00:00Z',is_read:false}]});
  });
  vi.stubGlobal('fetch',request);
  const {rerender}=render(<NotificationBell token="first" onNavigate={()=>{}} />);
  await waitFor(()=>expect(finishOld).toHaveLength(2));
  rerender(<NotificationBell token="second" onNavigate={()=>{}} />);
  await waitFor(()=>expect(document.querySelector('.notification-badge')?.textContent).toBe('1'));
  finishOld.forEach(resolve=>resolve());
  fireEvent.click(screen.getByRole('button',{name:'Notifications'}));
  expect(await screen.findByRole('button',{name:'New notice'})).toBeTruthy();
  expect(screen.queryByText('Old private notice')).toBeNull();
  expect(document.querySelector('.notification-badge').textContent).toBe('1');
});

it('closes with Escape and returns keyboard focus to the bell', async()=>{
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/unread-count')?{unread_count:1}:[{notification_id:9,manuscript_id:3,message:'Synthetic notice',created_at:'2026-01-01T00:00:00Z',is_read:false}]})));
  const user=userEvent.setup();render(<NotificationBell token="synthetic" onNavigate={()=>{}} />);
  const bell=screen.getByRole('button',{name:'Notifications'});
  await user.click(bell);
  const notice=await screen.findByRole('button',{name:'Synthetic notice'});
  notice.focus();await user.keyboard('{Escape}');
  expect(screen.queryByRole('button',{name:'Synthetic notice'})).toBeNull();
  expect(document.activeElement).toBe(bell);
  expect(bell.getAttribute('aria-expanded')).toBe('false');
});

it('opens with Space without marking notifications as read', async()=>{
  const request=vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/unread-count')?{unread_count:1}:[{notification_id:9,manuscript_id:3,message:'Synthetic unread',created_at:'2026-01-01T00:00:00Z',is_read:false}]}));
  vi.stubGlobal('fetch',request);
  const user=userEvent.setup();render(<NotificationBell token="synthetic" onNavigate={()=>{}} />);
  const bell=screen.getByRole('button',{name:'Notifications'});await user.tab();
  expect(document.activeElement).toBe(bell);await user.keyboard(' ');
  expect(await screen.findByRole('button',{name:'Synthetic unread'})).toBeTruthy();
  expect(bell.getAttribute('aria-expanded')).toBe('true');
  expect(request.mock.calls.some(([,options])=>options?.method==='PATCH')).toBe(false);
});

it('supports start-aligned placement without changing notification behavior',async()=>{
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.endsWith('/unread-count')?{unread_count:0}:[]})));
  const {container}=render(<NotificationBell token="synthetic" align="start" />);
  expect(container.querySelector('.notification-container-start')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Notifications'}));
  expect(await screen.findByText('No notifications yet.')).toBeTruthy();
});

it('does not show stale counts or an empty success state when refresh fails', async()=>{
  let fail=false;
  vi.stubGlobal('fetch',vi.fn(async url=>fail?{ok:false,json:async()=>({detail:'Unavailable'})}:{ok:true,json:async()=>url.endsWith('/unread-count')?{unread_count:3}:[]}));
  render(<NotificationBell token="synthetic" />);
  await screen.findByText('3');fail=true;
  fireEvent.click(screen.getByRole('button',{name:'Notifications'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Unavailable');
  expect(document.querySelector('.notification-badge')).toBeNull();
  expect(screen.queryByText('No notifications yet.')).toBeNull();
});

it('shows loading immediately and stays closed when Escape precedes a delayed response',async()=>{
  let release;
  const gate=new Promise(resolve=>{release=resolve;});
  vi.stubGlobal('fetch',vi.fn(async url=>{await gate;return {ok:true,json:async()=>url.endsWith('/unread-count')?{unread_count:0}:[]};}));
  const user=userEvent.setup();render(<NotificationBell token="synthetic" />);
  const bell=screen.getByRole('button',{name:'Notifications'});
  await user.click(bell);expect(screen.getByRole('status').textContent).toContain('Loading notifications');
  await user.keyboard('{Escape}');expect(bell.getAttribute('aria-expanded')).toBe('false');
  release();await waitFor(()=>expect(bell.getAttribute('aria-expanded')).toBe('false'));
  expect(screen.queryByText('No notifications yet.')).toBeNull();
});
