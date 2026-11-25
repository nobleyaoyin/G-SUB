import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react';
import AuthorNotificationCenter from './AuthorNotificationCenter';
afterEach(()=>{cleanup();vi.restoreAllMocks()});
it('stops a sequential mark-all operation when the center unmounts',async()=>{
 let finish;const markRead=vi.fn(()=>new Promise(resolve=>{finish=resolve}));
 const snapshot={token:'synthetic',state:'ready',items:[{notification_id:1,message:'One',is_read:false},{notification_id:2,message:'Two',is_read:false}],markRead};
 const {unmount}=render(<AuthorNotificationCenter snapshot={snapshot} token="synthetic" onBack={()=>{}} onOpen={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'Mark all as read'}));expect(markRead).toHaveBeenCalledTimes(1);unmount();await act(async()=>finish(true));expect(markRead).toHaveBeenCalledTimes(1);
});
it('presents a readable title and opens the associated process',()=>{
 const onOpen=vi.fn();const item={notification_id:3,manuscript_id:7,notification_type:'editor_update',message:'Synthetic',is_read:false};
 render(<AuthorNotificationCenter snapshot={{token:'synthetic',state:'ready',items:[item],markRead:vi.fn()}} token="synthetic" onBack={()=>{}} onOpen={onOpen}/>);
 expect(screen.getByText('Editor update')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Open process'}));expect(onOpen).toHaveBeenCalledWith(item);
});
it('displays the known system role label without altering the notification record',()=>{
 const item={notification_id:3,message:'AUTHOR reviewed final editing submission #1: approve.',is_read:false};
 render(<AuthorNotificationCenter snapshot={{token:'synthetic',state:'ready',items:[item],markRead:vi.fn()}} token="synthetic" onBack={()=>{}} onOpen={()=>{}}/>);
 expect(screen.getByText('Author reviewed final editing submission #1: approve.')).toBeTruthy();
 expect(item.message).toBe('AUTHOR reviewed final editing submission #1: approve.');
});
