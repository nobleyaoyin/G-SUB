import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import LifecycleAdministration from './LifecycleAdministration';
afterEach(()=>{cleanup();vi.restoreAllMocks();});
it('requires a reason and submits a confirmed enrollment through the API',async()=>{
 let state='not_enrolled';
 const fetchMock=vi.spyOn(globalThis,'fetch').mockImplementation(async(url,options={})=>{
  if(url.includes('/actions')){expect(JSON.parse(options.body)).toMatchObject({action:'enroll',reason:'Synthetic reason',expected_sequence:0,expected_generation:0});state='enrolled_not_active';return {ok:true,json:async()=>({status:state})};}
  if(url.includes('/history'))return {ok:true,json:async()=>({events:[],enrollment:null})};
  return {ok:true,json:async()=>[{user_id:12,name:'Synthetic EIC',state,sequence:0,generation:0}]};
 });
 vi.spyOn(window,'confirm').mockReturnValue(true);
 render(<LifecycleAdministration token="synthetic"/>);
 fireEvent.click(screen.getByText('Administrator: EIC lifecycle'));
 fireEvent.click(await screen.findByRole('button',{name:/Synthetic EIC/}));
 await screen.findByText(/State: Not enrolled/);
 expect(screen.getByRole('button',{name:'Enroll EIC'}).disabled).toBe(true);
 fireEvent.change(screen.getByLabelText('Reason'),{target:{value:'Synthetic reason'}});
 fireEvent.click(screen.getByRole('button',{name:'Enroll EIC'}));
 await waitFor(()=>expect(fetchMock.mock.calls.some(([url])=>url.includes('/actions'))).toBe(true));
 await screen.findByText(/Action recorded/);
});
it('reports denied access without exposing account information',async()=>{
 vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:false,status:403,json:async()=>({detail:'Administrator unavailable'})});
 render(<LifecycleAdministration token="synthetic"/>);
 fireEvent.click(screen.getByText('Administrator: EIC lifecycle'));
 expect((await screen.findByRole('alert')).textContent).toBe('Administrator unavailable');
});
it('does not offer the final administrator a self-disable action',async()=>{
 vi.spyOn(globalThis,'fetch').mockImplementation(async(url)=>url.includes('/history')
  ? {ok:true,json:async()=>({events:[],enrollment:null})}
  : {ok:true,json:async()=>[{user_id:1,name:'Synthetic Administrator',state:'active',sequence:1,generation:1}]});
 render(<LifecycleAdministration token="synthetic" currentUserId={1}/>);
 fireEvent.click(screen.getByText('Administrator: EIC lifecycle'));
 fireEvent.click(await screen.findByRole('button',{name:/Synthetic Administrator/}));
 expect(await screen.findByText(/cannot disable their own account/)).toBeTruthy();
 expect(screen.queryByRole('button',{name:'Disable EIC'})).toBeNull();
});
