import {workflowStatusLabel} from './workflowStatus';
import {useState} from 'react';
import {API_URL} from './api';
import './LifecycleAdministration.css';

export default function LifecycleAdministration({token,currentUserId,initialUsers=null}) {
  const [users,setUsers]=useState(initialUsers),[query,setQuery]=useState(''),[selected,setSelected]=useState(null);
  const [history,setHistory]=useState(null),[reason,setReason]=useState(''),[message,setMessage]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function request(path,options={}) {
    const response=await fetch(`${API_URL}${path}`,{...options,headers:{Authorization:`Bearer ${token}`,...options.headers}});
    if(!response.ok){const body=await response.json().catch(()=>({}));throw Error(typeof body.detail==='string'?body.detail:`Request failed (${response.status})`);}
    return response.json();
  }
  async function search() {
    setBusy(true);setError('');
    try {setUsers(await request(`/lifecycle-admin/eics?q=${encodeURIComponent(query)}`));}catch(e){setError(e.message);}finally{setBusy(false);}
  }
  async function select(user) {
    setSelected(user);setHistory(null);setReason('');setError('');setMessage('');setBusy(true);
    try{setHistory(await request(`/lifecycle-admin/eics/${user.user_id}/history`));}catch(e){setError(e.message);}finally{setBusy(false);}
  }
  async function act(action) {
    if (!reason.trim() || !window.confirm(`${action} lifecycle for EIC #${selected.user_id}?`))return;
    setBusy(true);setError('');setMessage('');
    try {
      const result=await request(`/lifecycle-admin/eics/${selected.user_id}/actions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,request_id:crypto.randomUUID(),reason:reason.trim(),expected_sequence:selected.sequence,expected_generation:selected.generation})});
      setMessage(`Action recorded: ${workflowStatusLabel(result.status)}.`);setReason('');
      const users=await request(`/lifecycle-admin/eics?q=${encodeURIComponent(query)}`);setUsers(users);
      setSelected(users.find(u=>u.user_id===selected.user_id)||null);
      setHistory(await request(`/lifecycle-admin/eics/${selected.user_id}/history`));
    }catch(e){setError(e.message);}finally{setBusy(false);}
  }
  const action=selected?.state==='not_enrolled'?'enroll':selected?.state==='enrolled_not_active'?'activate':selected?.state==='active'?'disable':selected?.state==='disabled'?'reactivate':null;
  return <details className="eic-context-panel" onToggle={e=>{if(e.currentTarget.open&&users===null&&!busy)search();}}><summary>Administrator: EIC lifecycle</summary><div className="eic-context-content lifecycle-admin">
    <p>Manage EIC account enrollment, activation and access history.</p>
    {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}{busy&&<p role="status">Loading or saving…</p>}
    <form onSubmit={e=>{e.preventDefault();search();}}><label>Search name or user ID <input value={query} onChange={e=>setQuery(e.target.value)} maxLength={100}/></label><button disabled={busy}>Search</button></form>
    {users&&!users.length&&<p>No matching EIC accounts.</p>}
    {users?.map(user=><button type="button" className="lifecycle-user" key={user.user_id} onClick={()=>select(user)} disabled={busy}>#{user.user_id} {user.name} — {workflowStatusLabel(user.state)}</button>)}
    {selected&&<section><h4>{selected.name} (EIC #{selected.user_id})</h4><p>State: {workflowStatusLabel(selected.state)} · Sequence: {selected.sequence??'Unavailable'} · Generation: {selected.generation??'Unavailable'}</p>
      {action==='disable'&&selected.user_id===currentUserId ? <p>The final administrator cannot disable their own account.</p> : action&&<><label>Reason <textarea value={reason} onChange={e=>setReason(e.target.value)} maxLength={1000}/></label><button type="button" disabled={busy||!reason.trim()} onClick={()=>act(action)}>{action[0].toUpperCase()+action.slice(1)} EIC</button></>}
      <h4>Lifecycle history</h4>{history?.enrollment&&<p>Enrollment: {history.enrollment.created_at} · {history.enrollment.reason}</p>}{history&&!history.events.length&&<p>No lifecycle events recorded.</p>}
      {history?.events.map(event=><article key={event.event_id}><p>#{event.sequence}: {event.from_state||'Not enrolled'} → {event.to_state} · Generation {event.generation}</p><p>{event.occurred_at} · {event.reason || event.reason_code}</p>{event.bootstrap_operator_fingerprint&&<p>Offline bootstrap approval: {event.bootstrap_approval_reference}</p>}</article>)}
    </section>}
  </div></details>;
}
