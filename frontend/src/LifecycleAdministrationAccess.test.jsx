import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import LifecycleAdministrationAccess from './LifecycleAdministrationAccess';
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
it('shows the existing panel only after a successful authorized response',async()=>{
 const request=vi.fn(async()=>({ok:true,json:async()=>[]}));vi.stubGlobal('fetch',request);
 render(<LifecycleAdministrationAccess token="synthetic" currentUserId={1}/>);
 expect(await screen.findByText('Administrator: EIC lifecycle')).toBeTruthy();
 expect(request.mock.calls[0][1].headers.Authorization).toBe('Bearer synthetic');
});
it.each([403,503])('does not expose lifecycle controls for an unsuccessful %s probe',async status=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status,json:async()=>({detail:'EIC proof schema unavailable'})})));
 render(<LifecycleAdministrationAccess token="synthetic" currentUserId={1}/>);
 await waitFor(()=>expect(fetch).toHaveBeenCalled());
 expect(screen.queryByText('Administrator: EIC lifecycle')).toBeNull();
 expect(screen.queryByText(/schema unavailable/)).toBeNull();
});
