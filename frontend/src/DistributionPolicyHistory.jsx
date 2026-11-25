import {displayError} from './displayError';
import {workflowStatusLabel} from './workflowStatus';
import {useEffect, useRef, useState} from 'react';
import {API_URL} from './api';

export default function DistributionPolicyHistory({token, manuscriptId, source}) {
  const [open,setOpen]=useState(false), [items,setItems]=useState(null), [error,setError]=useState(''), [busy,setBusy]=useState(false), [revision,setRevision]=useState(0);
  const [kind,setKind]=useState('initial'), [mode,setMode]=useState('manual');
  const [intents,setIntents]=useState(null), [intentError,setIntentError]=useState('');
  const [captureFailures,setCaptureFailures]=useState(null), [captureError,setCaptureError]=useState('');
  const scope=useRef({token,manuscriptId});
  if(scope.current.token!==token||scope.current.manuscriptId!==manuscriptId)scope.current={token,manuscriptId};
  useEffect(()=>{
    if(!open)return;
    const controller=new AbortController();setItems(null);setError('');
    fetch(`${API_URL}/document-distribution/manuscripts/${manuscriptId}/policies`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal})
      .then(async response=>{if(!response.ok)throw new Error('Policy history unavailable.');return response.json()})
      .then(data=>{if(!controller.signal.aborted)setItems(data.policies)})
      .catch(err=>{if(!controller.signal.aborted)setError(err.message)});
    return ()=>controller.abort();
  },[open,token,manuscriptId,revision]);
  const revoke=async item=>{
    const reason=window.prompt('Reason for revoking this policy:');if(!reason?.trim())return;
    setBusy(true);setError('');
    try {
      const response=await fetch(`${API_URL}/document-distribution/manuscripts/${manuscriptId}/policies/${item.policy_id}/revoke`,{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:JSON.stringify({reason})});
      if(!response.ok)throw new Error('Policy revocation unavailable.');
      setRevision(value=>value+1);
    } catch(err){setError(err.message)} finally {setBusy(false)}
  };
  const create=async()=>{
    if(!source?.sha256 || !window.confirm(`Authorize ${mode} distribution of the current ${source.format.toUpperCase()} source for ${kind} Editor assignments? Existing grants without current source provenance will not satisfy this policy.`))return;
    setBusy(true);setError('');
    try {
      const response=await fetch(`${API_URL}/document-distribution/manuscripts/${manuscriptId}/policies`,{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:JSON.stringify({invitation_kind:kind,mode,source_sha256:source.sha256,confirmed:true})});
      if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail || 'Policy authorization unavailable.')}
      setRevision(value=>value+1);
    } catch(err){setError(err.message)} finally {setBusy(false)}
  };
  const loadIntents=async()=>{
    const owner=scope.current;
    setIntentError('');
    try {
      const response=await fetch(`${API_URL}/document-distribution/manuscripts/${manuscriptId}/automatic-intents`,{headers:{Authorization:`Bearer ${token}`}});
      if(!response.ok)throw new Error('Automatic intent history unavailable.');
      const data=await response.json();if(scope.current===owner)setIntents(data);
    } catch(err){if(scope.current===owner){setIntents(null);setIntentError(err.message)}}
  };
  const loadCaptureFailures=async()=>{
    const owner=scope.current;setCaptureError('');
    try {
      const response=await fetch(`${API_URL}/document-distribution/manuscripts/${manuscriptId}/automatic-capture-failures`,{headers:{Authorization:`Bearer ${token}`}});
      if(!response.ok)throw new Error('Capture failure history unavailable.');
      const data=await response.json();if(scope.current===owner)setCaptureFailures(data);
    } catch(err){if(scope.current===owner){setCaptureFailures(null);setCaptureError(err.message)}}
  };
  const processIntent=async item=>{
    const owner=scope.current;setBusy(true);setIntentError('');
    try {
      const response=await fetch(`${API_URL}/document-distribution/manuscripts/${manuscriptId}/automatic-intents/${item.intent_id}/process`,{method:'POST',headers:{Authorization:`Bearer ${token}`}});
      if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||'Processing unavailable.')}
      if(scope.current===owner)await loadIntents();
    } catch(err){if(scope.current===owner)setIntentError(err.message)} finally {if(scope.current===owner)setBusy(false)}
  };
  return <details onToggle={event=>setOpen(event.currentTarget.open)}>
    <summary>Editor source policy history</summary>
    <p>Manual is the default. Automatic applies only to subsequent accepted Editor invitations.</p>
    <label>Distribution mode <select value={mode} onChange={event=>setMode(event.target.value)}><option value="manual">Manual</option><option value="automatic">Automatic</option></select></label>
    <label>Editor scope <select value={kind} onChange={event=>setKind(event.target.value)}><option value="initial">Initial editor</option><option value="final">Final editor</option></select></label>
    <button type="button" disabled={busy||!source?.sha256} onClick={create}>Authorize {mode==='manual'?'Manual':'Automatic'} policy</button>
    {error&&<p role="alert">{displayError(error)}</p>}
    {open&&!error&&items===null&&<p role="status">Loading policy history…</p>}
    {items?.length===0&&<p>No configured policies.</p>}
    {items?.length>0&&<ul>{items.map(item=><li key={item.policy_id}>
      {item.invitation_kind==='initial'?'Initial Editor':'Final Editor'} · {workflowStatusLabel(item.mode)} · version {item.version} · {workflowStatusLabel(item.status)} · authorized {item.authorized_at}
      {item.status==='active'&&<button type="button" disabled={busy} onClick={()=>revoke(item)}>Revoke policy</button>}
    </li>)}</ul>}
    <button type="button" onClick={loadIntents}>Load automatic intent history</button>
    {intentError&&<p role="alert">{displayError(intentError)}</p>}
    {intents?.length===0&&<p>No automatic intents recorded.</p>}
    {intents?.length>0&&<><p>Pending records do not grant document access.</p><ul>{intents.map(item=><li key={item.intent_id}>{item.invitation_kind==='initial'?'Initial Editor':'Final Editor'} · invitation #{item.invitation_id} · {workflowStatusLabel(item.state)}{item.reason_code==='round_evidence_required'?' · Review round evidence required; processing is blocked':item.reason_code?' · Processing unavailable':''} {item.retryable&&<button type="button" disabled={busy} onClick={()=>processIntent(item)}>Retry processing</button>}</li>)}</ul></>}
    <button type="button" onClick={loadCaptureFailures}>Load capture failures</button>
    {captureError&&<p role="alert">{displayError(captureError)}</p>}
    {captureFailures?.length===0&&<p>No capture failures recorded.</p>}
    {captureFailures?.length>0&&<ul>{captureFailures.map(item=><li key={item.failure_id}>{item.invitation_kind==='initial'?'Initial Editor':'Final Editor'} · invitation #{item.invitation_id} · capture unavailable · {item.occurred_at}</li>)}</ul>}
  </details>;
}
