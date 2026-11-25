import {workflowStatusLabel} from './workflowStatus';
import {useCallback, useEffect, useRef, useState} from 'react';
import {API_URL} from './api';
import {recordedTimestamp} from './recordedTimestamp';

const label = item => item.round_kind === 'pre_review' ? 'Pre-review' : `Review round ${item.review_round}`;
const people = item => item.participants.map(person => `${person.role}: ${person.name}`).join(', ');

export default function StageDialoguePanel({manuscriptId, token}) {
  const [open,setOpen]=useState(false), [threads,setThreads]=useState([]), [loaded,setLoaded]=useState(false), [stage,setStage]=useState('initial_editing');
  const [selected,setSelected]=useState(null), [conversation,setConversation]=useState(null), [audience,setAudience]=useState(null);
  const [body,setBody]=useState(''), [busy,setBusy]=useState(false), [error,setError]=useState('');
  const context=useRef({manuscriptId,token}), sequence=useRef(0), pendingKey=useRef(null);
  if(context.current.manuscriptId!==manuscriptId || context.current.token!==token){context.current={manuscriptId,token};sequence.current++;}
  useEffect(()=>{setThreads([]);setLoaded(false);setSelected(null);setConversation(null);setAudience(null);setBody('');setError('');setOpen(false);pendingKey.current=null;},[manuscriptId,token]);
  const request=useCallback(async (path, options={})=>{
    const response=await fetch(`${API_URL}/manuscripts/${manuscriptId}/dialogue${path}`,{...options,cache:'no-store',headers:{Authorization:`Bearer ${token}`,...(options.body?{'Content-Type':'application/json'}:{})}});
    const data=await response.json().catch(()=>null);
    if(!response.ok)throw new Error(data?.detail || 'Stage dialogue unavailable.');
    return data;
  },[manuscriptId,token]);
  const run=async (work)=>{
    const expected=context.current,version=++sequence.current;setBusy(true);setError('');
    try {await work(()=>context.current===expected && sequence.current===version);} catch(e){if(context.current===expected && sequence.current===version)setError(e.message || 'Stage dialogue unavailable.');}
    finally {if(context.current===expected && sequence.current===version)setBusy(false);}
  };
  const load=()=>run(async current=>{const data=await request('/threads');if(current()){setThreads(data);setLoaded(true);}});
  const show=thread=>run(async current=>{const data=await request(`/threads/${thread.thread_id}`);if(current()){setSelected(thread);setConversation(data);setAudience(null);setBody('');pendingKey.current=null;}});
  const review=target=>run(async current=>{
    const data=await request(`/audience-preview?stage=${encodeURIComponent(target)}`);
    if(current()){
      if(selected && (data.round_kind!==selected.round_kind || data.review_round!==selected.review_round || JSON.stringify(data.participants)!==JSON.stringify(selected.participants)))throw new Error('The current audience or stage differs from this thread.');
      setAudience(data);
    }
  });
  const create=()=>run(async current=>{
    const thread=await request('/threads',{method:'POST',body:JSON.stringify({stage})});
    const data=await request(`/threads/${thread.thread_id}`);
    if(current()){setThreads(previous=>previous.some(x=>x.thread_id===thread.thread_id)?previous:[...previous,thread]);setSelected(thread);setConversation(data);setAudience(null);}
  });
  const send=()=>run(async current=>{
    if(!pendingKey.current)pendingKey.current=crypto.randomUUID().replaceAll('-','');
    await request(`/threads/${selected.thread_id}/messages`,{method:'POST',body:JSON.stringify({body,idempotency_key:pendingKey.current})});
    const data=await request(`/threads/${selected.thread_id}`);
    if(current()){setConversation(data);setBody('');pendingKey.current=null;setAudience(null);}
  });
  return <details data-stage-dialogue open={open} onToggle={event=>{const value=event.currentTarget.open;setOpen(value);if(value && !open)load();}}>
    <summary>Stage Threads</summary>
    <div aria-busy={busy}>
      {error && <><p role="alert">{error}</p>{!loaded && <button type="button" disabled={busy} onClick={load}>Retry loading threads</button>}</>}
      {busy && <p role="status">Loading stage dialogue…</p>}
      {!busy && loaded && threads.length===0 && <p>No available stage threads.</p>}
      <ul>{threads.map(thread=><li key={thread.thread_id}><button type="button" disabled={busy} onClick={()=>show(thread)}>{workflowStatusLabel(thread.stage)} · {label(thread)}</button></li>)}</ul>
      {loaded && !selected && <><label>Stage <select disabled={busy} value={stage} onChange={event=>{setStage(event.target.value);setAudience(null);}}><option value="initial_editing">Initial editing</option><option value="final_editing">Final editing</option></select></label>{' '}
        <button type="button" disabled={busy} onClick={()=>review(stage)}>Preview audience</button>
        {audience && <><p>Visible to: {people(audience)} · {label(audience)}</p><button type="button" disabled={busy} onClick={create}>Open stage thread</button></>}</>}
      {selected && conversation && <section aria-label="Stage conversation"><h4>{workflowStatusLabel(selected.stage)} · {label(selected)}</h4><p>Visible to: {people(selected)}</p>
        {conversation.messages.length===0 ? <p>No messages yet.</p> : <ol>{conversation.messages.map(item=><li key={item.message_id}><strong>{item.sender}</strong>: {item.body} <small>· {recordedTimestamp(item.created_at)}</small></li>)}</ol>}
        <label>Message <textarea disabled={busy} maxLength={5000} value={body} onChange={event=>{setBody(event.target.value);pendingKey.current=null;}} /></label>{' '}
        <button type="button" disabled={busy} onClick={()=>review(selected.stage)}>Review audience before sending</button>{' '}
        {audience && <p>Will be visible to: {people(audience)} · {label(audience)}</p>}
        <button type="button" disabled={busy || !audience || !body.trim()} onClick={send}>Send message</button>{' '}
        <button type="button" disabled={busy} onClick={()=>{setSelected(null);setConversation(null);setAudience(null);setBody('');pendingKey.current=null;}}>Back to threads</button>
      </section>}
    </div>
  </details>;
}
