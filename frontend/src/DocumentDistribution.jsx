import {useCallback,useEffect,useRef,useState} from 'react';
import {API_URL} from './api';

async function request(token,path,options={}) {
  const response=await fetch(`${API_URL}/document-distribution${path}`,{...options,headers:{Authorization:`Bearer ${token}`,...options.headers}});
  if (!response.ok) { const body=await response.json().catch(()=>({})); throw new Error(body.detail || `Request failed (${response.status})`); }
  return response;
}
async function save(response,name,isCurrent=()=>true) {
  const blob=await response.blob();if(!isCurrent())return;
  const create=URL.createObjectURL, revoke=URL.revokeObjectURL;
  if(typeof create!=='function'||typeof revoke!=='function')throw new Error('Download unavailable');
  const url=create.call(URL,blob);
  try { const link=document.createElement('a'); link.href=url;link.download=name;link.click(); }
  finally { const cleanup=()=>{try{revoke.call(URL,url)}catch{}};try{setTimeout(cleanup,1000)}catch{cleanup()} }
}
function RecordedStageDocuments({overview, formatting, manuscriptId}) {
  if (overview?.manuscript?.manuscript_id !== manuscriptId) return <p>Stage document records unavailable.</p>;
  const initial=Array.isArray(overview.submissions)?overview.submissions:[];
  const final=Array.isArray(overview.final_workflow_submissions)?overview.final_workflow_submissions:[];
  const assignments=Array.isArray(overview.assignments)?overview.assignments:[];
  const bindings=[...new Map(assignments.map(item=>item.recorded_round_binding).filter(item=>item&&Number.isInteger(item.round_file_id)).map(item=>[item.round_file_id,item])).values()];
  const formatRecords=formatting?.manuscript_id===manuscriptId&&Array.isArray(formatting.submissions)?formatting.submissions:[];
  return <section aria-label="Recorded stage documents"><h4>Recorded stage documents</h4>
    <p>These records do not establish delivery or download; missing versions and digests are not reconstructed.</p>
    {!initial.length&&!final.length&&!bindings.length&&!formatRecords.length&&<p>No stage document records are available.</p>}
    <ul>
      {initial.map(item=><li key={`initial-${item.submission_id}`}>Initial editing · submission #{item.submission_id} · {item.status || 'Status unavailable'} · editor {item.editor || 'Unavailable'} · {item.created_at || 'Timestamp unavailable'} · version and SHA-256 not recorded here</li>)}
      {bindings.map(item=><li key={`round-${item.round_file_id}`}>Reviewer input · round {item.review_round ?? 'unavailable'} · source binding #{item.round_file_id} · {item.source_kind || 'Source unavailable'} · bound {item.bound_at || 'time unavailable'} · delivery and digest unknown</li>)}
      {final.map(item=><li key={`final-${item.submission_id}`}>Final editing · submission #{item.submission_id} · {item.status || 'Status unavailable'} · editor #{item.editor_id ?? 'unavailable'} · {item.created_at || 'Timestamp unavailable'} · version and SHA-256 not recorded here</li>)}
      {formatRecords.map(item=><li key={`format-${item.submission_id}`}>Formatting · submission #{item.submission_id} · {item.status || 'Status unavailable'} · {item.created_at || 'Timestamp unavailable'} · version and SHA-256 not recorded here</li>)}
    </ul>
    {!formatting&&<p>Formatting and publication records are unavailable in this view.</p>}
    {formatting?.manuscript_id===manuscriptId&&formatting.publication&&overview.manuscript.status==='published'&&<p>Publication recorded for formatting submission #{formatting.publication.submission_id} · {formatting.publication.published_at || 'Timestamp unavailable'}.</p>}
  </section>;
}

function ManuscriptVersionHistory({token,manuscriptId}) {
  const [state,setState]=useState({owner:null,items:null,error:''});
  const [query,setQuery]=useState('');
  const scope=useRef({token,manuscriptId});
  const active=useRef(true);
  useEffect(()=>{active.current=true;return()=>{active.current=false}},[]);
  if(scope.current.token!==token||scope.current.manuscriptId!==manuscriptId) scope.current={token,manuscriptId};
  useEffect(()=>{
    const owner=scope.current;const controller=new AbortController();
    setQuery('');setState({owner,items:null,error:''});
    fetch(`${API_URL}/manuscripts/${manuscriptId}/versions`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal})
      .then(async response=>{if(!response.ok)throw new Error(`Version history unavailable (${response.status}).`);const data=await response.json();if(!Array.isArray(data))throw new Error('Version history unavailable.');return data})
      .then(items=>{if(!controller.signal.aborted&&scope.current===owner)setState({owner,items,error:''})})
      .catch(error=>{if(!controller.signal.aborted&&scope.current===owner)setState({owner,items:null,error:error.message})});
    return ()=>controller.abort();
  },[token,manuscriptId]);
  const download=async item=>{
    const owner=scope.current;
    try {
      const response=await fetch(`${API_URL}/manuscripts/${manuscriptId}/versions/${encodeURIComponent(item.filename)}`,{headers:{Authorization:`Bearer ${token}`}});
      if(!response.ok)throw new Error(`Version download unavailable (${response.status}).`);
      await save(response,item.filename,()=>active.current&&scope.current===owner);
    } catch(error){if(active.current&&scope.current===owner)setState(previous=>({...previous,error:error.message}))}
  };
  const current=state.owner===scope.current;
  const items=current&&Array.isArray(state.items)?state.items:[];
  const visible=items.filter(item=>typeof item.filename==='string'&&item.filename.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <section aria-label="Manuscript file versions"><h4>Manuscript file versions</h4>
    <p>Stored files do not establish submission, release or delivery. Version numbers, dates and digests are not recorded by this listing.</p>
    {!current||(!state.items&&!state.error)?<p>Loading manuscript versions…</p>:null}
    {current&&state.error&&<p role="alert">{state.error}</p>}
    {current&&state.items&&<><label>Search manuscript filenames <input value={query} onChange={event=>setQuery(event.target.value)} /></label>
      {!visible.length?<p>{items.length?'No filenames match.':'No manuscript versions recorded.'}</p>:<ul>{visible.map(item=><li key={item.filename}>{item.filename} · {item.size_bytes==null?'Size unavailable':`${item.size_bytes} bytes`} · {item.is_current?'Current file':'Historical file'} · submission and transfer not recorded <button type="button" onClick={()=>download(item)}>Download version</button></li>)}</ul>}</>}
  </section>;
}

export function EICDistribution({token,manuscriptId,overview,formatting,onHistoryChange}) {
  const [candidates,setCandidates]=useState(null),[history,setHistory]=useState([]),[reviewed,setReviewed]=useState([]),[loaded,setLoaded]=useState(false),[recipient,setRecipient]=useState(''),[error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
  const [stateOwner,setStateOwner]=useState(null);
  const key=useRef(null);const active=useRef(true);
  const scope=useRef({token,manuscriptId});const sequence=useRef(0);
  if(scope.current.token!==token||scope.current.manuscriptId!==manuscriptId){scope.current={token,manuscriptId};sequence.current++;key.current=null;}
  useEffect(()=>{active.current=true;return()=>{active.current=false}},[]);
  const load=useCallback(async()=>{
    const expected=scope.current;const version=++sequence.current;
    const current=()=>active.current&&scope.current===expected&&version===sequence.current;
    if(current()){setLoaded(false);setCandidates(null)}
    try {
      const [a,b,c]=await Promise.all([request(token,`/manuscripts/${manuscriptId}/candidates`),request(token,`/manuscripts/${manuscriptId}/history`),request(token,`/manuscripts/${manuscriptId}/reviewed-documents`)]);
      const [aa,bb,cc]=await Promise.all([a.json(),b.json(),c.json()]);if(current()){setCandidates(aa);setHistory(bb);setReviewed(cc);setLoaded(true);setError('');onHistoryChange?.(manuscriptId,token,bb);}
    } catch (error) { if(current()) onHistoryChange?.(manuscriptId,token,null); throw error; }
  },[token,manuscriptId,onHistoryChange]);
  useEffect(()=>{const expected=scope.current;setStateOwner(expected);setRecipient('');setError('');setMessage('');setBusy(false);load().catch(e=>{if(active.current&&scope.current===expected){setError(e.message);onHistoryChange?.(manuscriptId,token,null)}})},[load,onHistoryChange,manuscriptId,token]);
  const currentView=stateOwner===scope.current;const shownCandidates=currentView?candidates:null;
  const send=async()=>{
    const expected=scope.current;const current=()=>active.current&&scope.current===expected;
    const selected=shownCandidates?.recipients?.find(item=>`${item.invitation_kind}:${item.invitation_id}`===recipient);if(!selected || !shownCandidates?.document)return;
    if(!window.confirm(`Grant ${selected.name} access to current ${shownCandidates.document.format.toUpperCase()} document with SHA-256 ${shownCandidates.document.sha256}?`))return;
    key.current ||= crypto.randomUUID().replaceAll('-','');setBusy(true);setError('');
    try { const response=await request(token,`/manuscripts/${manuscriptId}/grants`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({invitation_kind:selected.invitation_kind,invitation_id:selected.invitation_id,source_sha256:shownCandidates.document.sha256,idempotency_key:key.current})});const result=await response.json();if(current()){setMessage(`Access granted (${result.grant_id}). Email not requested.`);key.current=null;try{await load()}catch{if(current())setError('Grant saved, but history could not be refreshed. Reopen this view to check it.')}} }
    catch(e){if(current())setError(`${e.message}. Retry with the same selection to reconcile.`)}finally{if(current())setBusy(false)}
  };
  const revoke=async id=>{const expected=scope.current;const current=()=>active.current&&scope.current===expected;const reason=window.prompt('Reason for revoking access:');if(!reason?.trim())return;setBusy(true);try{await request(token,`/grants/${id}/revoke`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});if(current())await load()}catch(e){if(current())setError(e.message)}finally{if(current())setBusy(false)}};
  return <details className="eic-context-panel"><summary>Document distribution and generation history</summary><div className="eic-context-content">
    {currentView&&error&&<p role="alert">{error}</p>}{currentView&&message&&<p role="status">{message}</p>}
    <p>Distribution mode: Manual. Automatic distribution is unavailable until its trigger and recipient policy are approved.</p>
    {shownCandidates?.document&&<><p><strong>Document:</strong> Current manuscript · {shownCandidates.document.format.toUpperCase()} · {shownCandidates.document.byte_size} bytes</p><p>Version SHA-256: <code>{shownCandidates.document.sha256}</code></p>
      <label>Accepted editor <select value={recipient} onChange={e=>{setRecipient(e.target.value);key.current=null}}><option value="">Select recipient</option>{shownCandidates.recipients.map(item=><option key={`${item.invitation_kind}-${item.invitation_id}`} value={`${item.invitation_kind}:${item.invitation_id}`}>{item.name} · {item.invitation_kind} #{item.invitation_id}</option>)}</select></label>
      <button type="button" disabled={busy||recipient===''} onClick={send}>Confirm manual distribution</button></>}
    <RecordedStageDocuments overview={overview} formatting={formatting} manuscriptId={manuscriptId} />
    <ManuscriptVersionHistory token={token} manuscriptId={manuscriptId} />
    <h4>Outgoing grants</h4>{!currentView||!loaded?<p>History loading or unavailable.</p>:history.length===0?<p>No recorded grants; legacy delivery is unknown.</p>:<ul>{history.map(item=><li key={item.grant_id}>Version {item.version} · Editor #{item.recipient_id} · {item.invitation_kind} invitation #{item.invitation_id} · EIC #{item.actor_id} · {item.status} · notification {item.notification} · email {item.email} · {item.created_at} · SHA-256 {item.sha256} {item.status==='access_granted'&&<button disabled={busy} onClick={()=>revoke(item.grant_id)}>Revoke access</button>}</li>)}</ul>}
    <h4>Incoming reviewed documents</h4>{!currentView||!loaded?<p>Reviewed document history loading or unavailable.</p>:reviewed.length===0?<p>No reviewed documents recorded.</p>:<ul>{reviewed.map(item=><li key={item.artifact_id}>Round {item.review_round} · assignment #{item.assignment_id} · version {item.version} · {item.format.toUpperCase()} · {item.byte_size ?? "Unavailable"} bytes · {item.created_at || "Timestamp unavailable"} · SHA-256 {item.sha256 || "Unavailable"} · delivery unknown <button onClick={()=>{const expected=scope.current;const current=()=>active.current&&scope.current===expected;request(token,`/reviewed-documents/${item.artifact_id}/download`).then(r=>save(r,`reviewed-document.${item.format}`,current)).catch(e=>{if(current())setError(e.message)})}} >Download reviewed document</button></li>)}</ul>}
  </div></details>;
}
export function EditorReceivedDocuments({token}) {
 const [items,setItems]=useState([]),[error,setError]=useState(''),[owner,setOwner]=useState(null);const current=useRef(token),mounted=useRef(false);current.current=token;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 useEffect(()=>{let active=true;request(token,'/my').then(r=>r.json()).then(data=>{if(active){setItems(data);setOwner(token);setError('')}}).catch(e=>{if(active){setItems([]);setOwner(token);setError(e.message)}});return()=>{active=false}},[token]);
 if(owner!==token||!items.length)return null;
 return <section aria-label="Received editorial documents"><h2>Received editorial documents</h2><ul>{items.map(item=><li key={item.grant_id}>{item.title} · version {item.version} · {item.format.toUpperCase()} <button onClick={()=>request(token,`/grants/${item.grant_id}/download`).then(r=>save(r,`editor-document.${item.format}`,()=>mounted.current&&current.current===token)).catch(e=>{if(mounted.current&&current.current===token)setError(e.message)})}>Download distributed document</button></li>)}</ul>{error&&<p role="alert">{error}</p>}</section>;
}
export function ReviewerDocumentUpload({token,assignmentId}) {
 const [file,setFile]=useState(null),[error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[available,setAvailable]=useState(false);const key=useRef(null);
 useEffect(()=>{let active=true;setAvailable(false);request(token,`/review-assignments/${assignmentId}/upload-availability`).then(r=>r.json()).then(data=>{if(active)setAvailable(data.available===true)}).catch(()=>{});return()=>{active=false}},[token,assignmentId]);
 const send=async e=>{e.preventDefault();if(!file)return;key.current ||= crypto.randomUUID().replaceAll('-','');setBusy(true);setError('');const body=new FormData();body.append('file',file);
  try{const r=await request(token,`/review-assignments/${assignmentId}/documents`,{method:'POST',headers:{'Idempotency-Key':key.current},body});const value=await r.json();setMessage(`Reviewed document saved: round ${value.review_round}, version ${value.version}.`);key.current=null;setFile(null)}catch(e){setError(`${e.message}. Retry with the same file.`)}finally{setBusy(false)}};
 if(!available)return null;
 return <form onSubmit={send}><h4>Reviewed document (editorial only)</h4><label>Reviewed file <input type="file" accept=".pdf,.docx,.doc,.txt" onChange={e=>{setFile(e.target.files[0]||null);key.current=null}} /></label> <button disabled={busy||!file}>Upload reviewed document</button>{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}</form>;
}
