import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import DistributionPolicyHistory from './DistributionPolicyHistory';

afterEach(()=>{cleanup();vi.unstubAllGlobals()});

it('loads policy history only when opened and revokes an active policy explicitly',async()=>{
  let revoked=false;
  const fetcher=vi.fn(async(_url,options={})=>({ok:true,json:async()=>({policies:[{
    policy_id:'a'.repeat(32),invitation_kind:'initial',mode:'manual',version:1,
    status:revoked?'revoked':'active',authorized_at:'synthetic',
  }]})}));
  fetcher.mockImplementation(async(_url,options={})=>{
    if(options.method==='POST')revoked=true;
    return {ok:true,json:async()=>({policies:[{policy_id:'a'.repeat(32),invitation_kind:'initial',mode:'manual',version:1,status:revoked?'revoked':'active',authorized_at:'synthetic'}]})};
  });
  vi.stubGlobal('fetch',fetcher);vi.stubGlobal('prompt',()=> 'Synthetic reason');
  render(<DistributionPolicyHistory token="synthetic" manuscriptId={3}/>);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('Editor source policy history'));
  expect(await screen.findByText(/Initial Editor · Manual · version 1 · Active/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Revoke policy'}));
  await waitFor(()=>expect(screen.getByText(/version 1 · Revoked/)).toBeTruthy());
  expect(fetcher.mock.calls.filter(([,options])=>options.method==='POST')).toHaveLength(1);
});

it('requires confirmation and sends only the selected Manual scope and current digest',async()=>{
  const fetcher=vi.fn(async(_url,options={})=>({ok:true,json:async()=>({policies:[]})}));
  vi.stubGlobal('fetch',fetcher);vi.stubGlobal('confirm',()=>true);
  render(<DistributionPolicyHistory token="synthetic" manuscriptId={3} source={{sha256:'b'.repeat(64),format:'txt'}}/>);
  fireEvent.click(screen.getByText('Editor source policy history'));
  await screen.findByText('No configured policies.');
  fireEvent.change(screen.getByLabelText('Editor scope'),{target:{value:'final'}});
  fireEvent.click(screen.getByRole('button',{name:'Authorize Manual policy'}));
  await waitFor(()=>expect(fetcher.mock.calls.some(([,options])=>options.method==='POST')).toBe(true));
  const sent=fetcher.mock.calls.find(([,options])=>options.method==='POST');
  expect(JSON.parse(sent[1].body)).toEqual({invitation_kind:'final',mode:'manual',source_sha256:'b'.repeat(64),confirmed:true});
});

it('allows explicit Automatic selection for an Editor scope',async()=>{
  const fetcher=vi.fn(async()=>({ok:true,json:async()=>({policies:[]})}));
  vi.stubGlobal('fetch',fetcher);vi.stubGlobal('confirm',()=>true);
  render(<DistributionPolicyHistory token="synthetic" manuscriptId={3} source={{sha256:'c'.repeat(64),format:'txt'}}/>);
  fireEvent.click(screen.getByText('Editor source policy history'));
  await screen.findByText('No configured policies.');
  expect(screen.getByLabelText('Distribution mode').value).toBe('manual');
  fireEvent.change(screen.getByLabelText('Distribution mode'),{target:{value:'automatic'}});
  fireEvent.click(screen.getByRole('button',{name:'Authorize Automatic policy'}));
  await waitFor(()=>expect(fetcher.mock.calls.some(([,options])=>options.method==='POST')).toBe(true));
  const sent=fetcher.mock.calls.find(([,options])=>options.method==='POST');
  expect(JSON.parse(sent[1].body)).toMatchObject({invitation_kind:'initial',mode:'automatic',confirmed:true});
  expect(screen.queryByRole('option',{name:/reviewer/i})).toBeNull();
});

it('shows pending automatic intents without claiming document access',async()=>{
  vi.stubGlobal('fetch',vi.fn(async(url)=>({ok:true,json:async()=>url.endsWith('/automatic-intents')
    ?[{intent_id:'synthetic',invitation_kind:'initial',invitation_id:4,state:'pending'}]
    :{policies:[]}})));
  render(<DistributionPolicyHistory token="synthetic" manuscriptId={3}/>);
  fireEvent.click(screen.getByText('Editor source policy history'));
  await screen.findByText('No configured policies.');
  fireEvent.click(screen.getByRole('button',{name:'Load automatic intent history'}));
  expect(await screen.findByText(/Initial Editor · invitation #4 · Pending/)).toBeTruthy();
  expect(screen.getByText(/Pending records do not grant document access/)).toBeTruthy();
});

it('shows a sanitized capture failure without implying a grant or retry',async()=>{
  vi.stubGlobal('fetch',vi.fn(async(url)=>({ok:true,json:async()=>url.endsWith('/automatic-capture-failures')
    ?[{failure_id:'synthetic',invitation_kind:'final',invitation_id:7,reason_code:'capture_unavailable',occurred_at:'synthetic'}]
    :{policies:[]}})));
  render(<DistributionPolicyHistory token="synthetic" manuscriptId={3}/>);
  fireEvent.click(screen.getByText('Editor source policy history'));
  await screen.findByText('No configured policies.');
  fireEvent.click(screen.getByRole('button',{name:'Load capture failures'}));
  expect(await screen.findByText(/Final Editor · invitation #7 · capture unavailable/)).toBeTruthy();
  expect(screen.queryByRole('button',{name:/retry/i})).toBeNull();
});

it('offers retry for server-eligible failed intents and refreshes status',async()=>{
  let granted=false;
  const fetcher=vi.fn(async(url,options={})=>{
    if(options.method==='POST')granted=true;
    return {ok:true,json:async()=>url.endsWith('/automatic-intents')
      ?[{intent_id:'a'.repeat(32),invitation_kind:'final',invitation_id:7,state:granted?'granted':'failed',retryable:!granted,reason_code:granted?null:'processing_unavailable'}]
      :{policies:[]}};
  });
  vi.stubGlobal('fetch',fetcher);
  render(<DistributionPolicyHistory token="synthetic" manuscriptId={3}/>);
  fireEvent.click(screen.getByText('Editor source policy history'));
  await screen.findByText('No configured policies.');
  fireEvent.click(screen.getByRole('button',{name:'Load automatic intent history'}));
  fireEvent.click(await screen.findByRole('button',{name:'Retry processing'}));
  expect(await screen.findByText(/Final Editor · invitation #7 · Granted/)).toBeTruthy();
  expect(fetcher.mock.calls.filter(([,options])=>options.method==='POST')).toHaveLength(1);
});

it('shows an unbound legacy intent as blocked without retry or grant',async()=>{
  vi.stubGlobal('fetch',vi.fn(async(url)=>({ok:true,json:async()=>url.endsWith('/automatic-intents')
    ?[{intent_id:'synthetic',invitation_kind:'initial',invitation_id:4,state:'blocked',reason_code:'round_evidence_required',retryable:false}]
    :{policies:[]}})));
  render(<DistributionPolicyHistory token="synthetic" manuscriptId={3}/>);
  fireEvent.click(screen.getByText('Editor source policy history'));
  await screen.findByText('No configured policies.');
  fireEvent.click(screen.getByRole('button',{name:'Load automatic intent history'}));
  expect(await screen.findByText(/Review round evidence required; processing is blocked/)).toBeTruthy();
  expect(screen.queryByRole('button',{name:'Retry processing'})).toBeNull();
  expect(screen.queryByText(/invitation #4 · Granted/)).toBeNull();
});
