import {workflowStatusLabel} from './workflowStatus';
import {useCallback,useEffect,useRef,useState} from 'react';
import {API_URL} from './api';
import DistributionPolicyHistory from './DistributionPolicyHistory';
import EICDocumentTimeline from './EICDocumentTimeline';
import {documentExtension, originalDocumentName} from './documentNames';
import {readableRecordedDate} from './recordedDisplay';
import {displayError} from './displayError';

function roundLabel(item) {
  if(item.round_kind==='pre_review')return 'Pre-review';
  if(item.round_kind==='review_round' && Number.isInteger(item.review_round) && item.review_round>0)return `Review round ${item.review_round}`;
  return 'Review round unavailable';
}
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
      {initial.map(item=><li key={`initial-${item.submission_id}`}>Initial editing · submission #{item.submission_id}{item.status && ` · ${workflowStatusLabel(item.status)}`}{item.editor && ` · Editor: ${item.editor}`}{readableRecordedDate(item.created_at) && ` · ${readableRecordedDate(item.created_at)}`}</li>)}
      {bindings.map(item=><li key={`round-${item.round_file_id}`}>Reviewer input{item.review_round != null && ` · Round ${item.review_round}`} · source binding #{item.round_file_id}{item.source_kind && ` · ${item.source_kind}`}{readableRecordedDate(item.bound_at) && ` · ${readableRecordedDate(item.bound_at)}`} · delivery not confirmed</li>)}
      {final.map(item=><li key={`final-${item.submission_id}`}>Final editing · submission #{item.submission_id}{item.status && ` · ${workflowStatusLabel(item.status)}`}{item.editor_id != null && ` · Editor #${item.editor_id}`}{readableRecordedDate(item.created_at) && ` · ${readableRecordedDate(item.created_at)}`}</li>)}
      {formatRecords.map(item=><li key={`format-${item.submission_id}`}>Formatting · submission #{item.submission_id}{item.status && ` · ${workflowStatusLabel(item.status)}`}{readableRecordedDate(item.created_at) && ` · ${readableRecordedDate(item.created_at)}`}</li>)}
    </ul>
    {!formatting&&<p>Formatting and publication records are unavailable in this view.</p>}
    {formatting?.manuscript_id===manuscriptId&&formatting.publication&&overview.manuscript.status==='published'&&<p>Publication recorded for formatting submission #{formatting.publication.submission_id}{readableRecordedDate(formatting.publication.published_at) && ` · ${readableRecordedDate(formatting.publication.published_at)}`}.</p>}
  </section>;
}

export function ManuscriptVersionHistory({token,manuscriptId,onCurrentVersion,historyOnly=false,authorView=false}) {
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
      .then(items=>{if(!controller.signal.aborted&&scope.current===owner){setState({owner,items,error:''});const current=items.filter(item=>item.is_current===true);onCurrentVersion?.(current.length===1 ? current[0] : null)}})
      .catch(error=>{if(!controller.signal.aborted&&scope.current===owner){setState({owner,items:null,error:error.message});onCurrentVersion?.(null)}});
    return ()=>controller.abort();
  },[token,manuscriptId,onCurrentVersion]);
  const download=async item=>{
    const owner=scope.current;
    try {
      const response=await fetch(`${API_URL}/manuscripts/${manuscriptId}/versions/${encodeURIComponent(item.filename)}`,{headers:{Authorization:`Bearer ${token}`}});
      if(!response.ok)throw new Error(`Version download unavailable (${response.status}).`);
      const extension=documentExtension(item);
      const name=authorView ? (originalDocumentName(item) || `previous-document${extension ? `.${extension}` : ''}`) : item.filename;
      await save(response,name,()=>active.current&&scope.current===owner);
    } catch(error){if(active.current&&scope.current===owner)setState(previous=>({...previous,error:error.message}))}
  };
  const current=state.owner===scope.current;
  const items=current&&Array.isArray(state.items)?state.items:[];
  const eligible=items.filter(item=>!historyOnly || item.is_current===false);
  const visible=eligible.filter(item=>typeof item.filename==='string'&&(authorView ? (originalDocumentName(item) || 'Previous document') : item.filename).toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  if (authorView) return <section className="wizard-version-history" aria-label="Manuscript file versions"><h4>Previous versions</h4>
    {!current||(!state.items&&!state.error)?<p role="status">Loading version history…</p>:null}
    {current&&state.error&&<p role="alert">{displayError(state.error)}</p>}
    {current&&state.items&&<><label className="wizard-version-search">Search document names <input value={query} onChange={event=>setQuery(event.target.value)} /></label>
      {!visible.length?<p>{eligible.length?'No document names match.':'No previous versions recorded.'}</p>:<ul className="wizard-version-list">{visible.map(item=>{
        const format=documentExtension(item);
        const details=[format && format.toUpperCase(), Number.isInteger(item.size_bytes) && item.size_bytes >= 0 && `${item.size_bytes} bytes`, Number.isInteger(item.version_number) && item.version_number > 0 && `Version ${item.version_number}`].filter(Boolean);
        return <li className="wizard-version-card" key={item.filename}><div><strong>{originalDocumentName(item) || 'Previous document'}</strong>{!originalDocumentName(item)&&<span> · Filename unavailable</span>}{details.length>0 && <p>{details.join(' · ')}</p>}</div><button type="button" className="wizard-secondary" onClick={()=>download(item)}>Download version</button></li>;
      })}</ul>}</>}
  </section>;
  return <section aria-label="Manuscript file versions"><h4>Manuscript file versions</h4>
    <p>Stored files do not establish submission, release or delivery. Version numbers, dates and digests are not recorded by this listing.</p>
    {!current||(!state.items&&!state.error)?<p>Loading manuscript versions…</p>:null}
    {current&&state.error&&<p role="alert">{displayError(state.error)}</p>}
    {current&&state.items&&<><label>Search manuscript filenames <input value={query} onChange={event=>setQuery(event.target.value)} /></label>
      {!visible.length?<p>{eligible.length?'No filenames match.':historyOnly?'No previous versions recorded.':'No manuscript versions recorded.'}</p>:<ul>{visible.map(item=><li key={item.filename}>{item.filename} · {item.size_bytes==null?'Size unavailable':`${item.size_bytes} bytes`} · {item.is_current?'Current file':'Historical file'} · submission and transfer not recorded <button type="button" onClick={()=>download(item)}>Download version</button></li>)}</ul>}</>}
  </section>;
}

function EditorInvitationRevocations({token,manuscriptId,onChanged}) {
 const [items,setItems]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const load=async()=>{const r=await request(token,`/manuscripts/${manuscriptId}/editor-invitations`);setItems(await r.json());setError('')};
 useEffect(()=>{const controller=new AbortController();setItems(null);setError('');
  request(token,`/manuscripts/${manuscriptId}/editor-invitations`,{signal:controller.signal}).then(r=>r.json()).then(data=>{if(!Array.isArray(data))throw new Error('unavailable');if(!controller.signal.aborted)setItems(data)})
   .catch(()=>{if(!controller.signal.aborted)setError('Editor invitations could not be loaded.')});
  return()=>controller.abort();
 },[token,manuscriptId]);
 const revoke=async item=>{const reason=window.prompt('Reason for revoking this editor invitation:');if(!reason?.trim())return;
  setBusy(true);setError('');try{await request(token,`/manuscripts/${manuscriptId}/editor-invitations/${item.invitation_kind}/${item.invitation_id}/revoke`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});await load();await onChanged?.()}catch(e){setError(e.message)}finally{setBusy(false)}};
 return <section aria-label="Editor invitation history"><h4>Editor invitation history</h4>{error&&<p role={items ? "alert" : "status"}>{displayError(error)}</p>}{!items&&!error&&<p>Loading editor invitations…</p>}{items&&(!items.length?<p>No editor invitations.</p>:<ul>{items.map(item=><li key={`${item.invitation_kind}:${item.invitation_id}`}>{item.invitation_kind==='initial'?'Initial':'Final'} Editor #{item.recipient_id} · invitation #{item.invitation_id} · {workflowStatusLabel(item.status)}{item.revoked_at&&<> · original status {workflowStatusLabel(item.original_status)} · revoked{readableRecordedDate(item.revoked_at) && ` ${readableRecordedDate(item.revoked_at)}`} by EIC #{item.revoked_by} · reason: {item.reason} · replacement unavailable in the current workflow</>}{['pending','accepted'].includes(item.status)&&<button type="button" disabled={busy} onClick={()=>revoke(item)}>Revoke invitation</button>}</li>)}</ul>)}</section>;
}

export function EICDistribution({token,manuscriptId,overview,formatting,onHistoryChange,revision=0}) {
  const [candidates,setCandidates]=useState(null),[history,setHistory]=useState([]),[reviewed,setReviewed]=useState([]),[loaded,setLoaded]=useState(false),[reviewedLoaded,setReviewedLoaded]=useState(false),[recipient,setRecipient]=useState(''),[documentDigest,setDocumentDigest]=useState(''),[error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
  const [stateOwner,setStateOwner]=useState(null),[timelineRevision,setTimelineRevision]=useState(0);
  const key=useRef(null);const active=useRef(true);
  const scope=useRef({token,manuscriptId});const sequence=useRef(0);
  if(scope.current.token!==token||scope.current.manuscriptId!==manuscriptId){scope.current={token,manuscriptId};sequence.current++;key.current=null;}
  useEffect(()=>{active.current=true;return()=>{active.current=false}},[]);
  const load=useCallback(async()=>{
    const expected=scope.current;const version=++sequence.current;
    const current=()=>active.current&&scope.current===expected&&version===sequence.current;
    if(current()){setLoaded(false);setReviewedLoaded(false);setCandidates(null)}
    try {
      const results=await Promise.allSettled([request(token,`/manuscripts/${manuscriptId}/candidates`).then(r=>r.json()),request(token,`/manuscripts/${manuscriptId}/history`).then(r=>r.json()),request(token,`/manuscripts/${manuscriptId}/reviewed-documents`).then(r=>r.json())]);
      const [a,b,c]=results;
      if(current() && c.status==='fulfilled' && Array.isArray(c.value)){setReviewed(c.value);setReviewedLoaded(true)}
      if(a.status==='rejected')throw a.reason;
      if(b.status==='rejected')throw b.reason;
      if(c.status==='rejected')throw c.reason;
      if(!Array.isArray(c.value))throw new Error('Reviewed document history unavailable.');
      if(current()){setCandidates(a.value);setHistory(b.value);setLoaded(true);setError('');onHistoryChange?.(manuscriptId,token,b.value);}
    } catch (error) { if(current()) onHistoryChange?.(manuscriptId,token,null); throw error; }
  },[token,manuscriptId,onHistoryChange]);
  useEffect(()=>{const expected=scope.current;setStateOwner(expected);setRecipient('');setDocumentDigest('');setError('');setMessage('');setBusy(false);load().catch(e=>{if(active.current&&scope.current===expected){setError(e.message);onHistoryChange?.(manuscriptId,token,null)}})},[load,onHistoryChange,manuscriptId,token]);
  const currentView=stateOwner===scope.current;const shownCandidates=currentView?candidates:null;
  const send=async()=>{
    const expected=scope.current;const current=()=>active.current&&scope.current===expected;
    const selected=shownCandidates?.recipients?.find(item=>`${item.invitation_kind}:${item.invitation_id}`===recipient);if(!selected || !shownCandidates?.document || documentDigest!==shownCandidates.document.sha256)return;
    if(!window.confirm(`Grant ${selected.name} access to current ${shownCandidates.document.format.toUpperCase()} document with SHA-256 ${shownCandidates.document.sha256}?`))return;
    key.current ||= crypto.randomUUID().replaceAll('-','');setBusy(true);setError('');setMessage('');
    try { const response=await request(token,`/manuscripts/${manuscriptId}/grants`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({invitation_kind:selected.invitation_kind,invitation_id:selected.invitation_id,source_sha256:documentDigest,idempotency_key:key.current})});const result=await response.json();if(current()){setTimelineRevision(value=>value+1);setMessage(result.already_exists ? `Existing access grant (${result.grant_id}); no new delivery recorded. Email not requested.` : `Access granted (${result.grant_id}). In-app notification recorded; email not requested. Download is not confirmed.`);key.current=null;try{await load()}catch{if(current())setError('Grant saved, but history could not be refreshed. Reopen this view to check it.')}} }
    catch(e){if(current())setError(`${e.message}. Retry with the same selection to reconcile.`)}finally{if(current())setBusy(false)}
  };
  const revoke=async id=>{const expected=scope.current;const current=()=>active.current&&scope.current===expected;const reason=window.prompt('Reason for revoking access:');if(!reason?.trim())return;setBusy(true);try{await request(token,`/grants/${id}/revoke`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});if(current()){setTimelineRevision(value=>value+1);await load()}}catch(e){if(current())setError(e.message)}finally{if(current())setBusy(false)}};
  return <details className="eic-context-panel"><summary>Document distribution and generation history</summary><div className="eic-context-content">
    {currentView&&error&&<><p role="alert">{displayError(error)}</p>{error !== 'Distribution schema unavailable' && <button type="button" disabled={busy} onClick={()=>{const pending=load(), version=sequence.current;pending.catch(e=>{if(active.current&&scope.current.token===token&&scope.current.manuscriptId===manuscriptId&&sequence.current===version)setError(e.message)})}}>Retry distribution data</button>}</>}{currentView&&message&&<p role="status">{message}</p>}
    <p>Distribution defaults to Manual. Automatic distribution requires an explicit policy.</p>
    <EditorInvitationRevocations key={`invitations:${manuscriptId}:${token}`} token={token} manuscriptId={manuscriptId} onChanged={load} />
    <DistributionPolicyHistory key={`${manuscriptId}:${token}`} token={token} manuscriptId={manuscriptId} source={shownCandidates?.document} />
    {shownCandidates?.document&&<><p><strong>Document:</strong> Current manuscript · {shownCandidates.document.format.toUpperCase()} · {shownCandidates.document.byte_size} bytes</p><p>Version SHA-256: <code>{shownCandidates.document.sha256}</code></p>
      <label>Document version <select value={documentDigest} onChange={e=>{setDocumentDigest(e.target.value);key.current=null}}><option value="">Select document version</option><option value={shownCandidates.document.sha256}>Current manuscript · {shownCandidates.document.format.toUpperCase()} · SHA-256 {shownCandidates.document.sha256}</option></select></label>
      <label>Accepted editor <select value={recipient} onChange={e=>{setRecipient(e.target.value);key.current=null}}><option value="">Select recipient</option>{shownCandidates.recipients.map(item=><option key={`${item.invitation_kind}-${item.invitation_id}`} value={`${item.invitation_kind}:${item.invitation_id}`}>{item.name} · {item.invitation_kind} #{item.invitation_id}</option>)}</select></label>
      <button type="button" disabled={busy||recipient===''||documentDigest!==shownCandidates.document.sha256} onClick={send}>Confirm manual distribution</button></>}
    <RecordedStageDocuments overview={overview} formatting={formatting} manuscriptId={manuscriptId} />
    <EICDocumentTimeline token={token} manuscriptId={manuscriptId} revision={`${revision}:${timelineRevision}`} onDownload={item=>{const expected=scope.current;const current=()=>active.current&&scope.current===expected;const kind=item.kind==='formatting'?'formatting':item.kind==='author_submission'?'submissions':item.kind==='final_editing'?'final-editing':'reviewed';fetch(`${API_URL}/eic/manuscripts/${manuscriptId}/document-timeline/${kind}/${encodeURIComponent(item.id)}/download`,{headers:{Authorization:`Bearer ${token}`}}).then(r=>{if(!r.ok)throw new Error('Document unavailable');const types={'application/pdf':'.pdf','text/plain':'.txt','application/msword':'.doc','application/vnd.openxmlformats-officedocument.wordprocessingml.document':'.docx'};const ext=types[(r.headers.get('content-type')||'').split(';')[0]]||'';return save(r,`${kind}-document${ext}`,current)}).catch(e=>{if(current())setError(e.message)})}} />
    <ManuscriptVersionHistory token={token} manuscriptId={manuscriptId} />
    <section aria-label="Review assignments and submissions"><h4>Review assignments and submissions</h4>
      {overview?.manuscript?.manuscript_id !== manuscriptId || !Array.isArray(overview?.assignments) ? <p>Review assignment history unavailable.</p> : overview.assignments.length === 0 ? <p>No review assignments recorded.</p> : overview.assignments.map(item => {
        const assignmentDocuments = reviewed.filter(document => document.assignment_id === item.assignment_id);
        const documents = assignmentDocuments.filter(document => document.review_round === item.review_round);
        const inconsistent = assignmentDocuments.length !== documents.length || !Number.isInteger(item.review_round) || item.review_round < 1;
        const round = Number.isInteger(item.review_round) && item.review_round > 0 ? `Review round ${item.review_round}` : 'Review round unavailable';
        return <article key={item.assignment_id}>
          <h5>{round} · Assignment #{item.assignment_id}</h5>
          <p>Assignment status: {item.status || 'unavailable'} · Invitation: {item.invitation_status || 'unavailable'}</p>
          <p>Received document: {item.recorded_round_binding ? `round source binding #${item.recorded_round_binding.round_file_id}; receipt not recorded` : 'assignment source evidence unavailable in this view'}</p>
          <p>Review comments: {item.review ? 'submitted' : 'not submitted'}{readableRecordedDate(item.review?.submitted_at) && ` · ${readableRecordedDate(item.review.submitted_at)}`}</p>
          {item.review && <><p>Recommendation: {item.review.recommendation || 'unavailable'}</p><p>{item.review.comments || 'No review comments recorded.'}</p></>}
          {!currentView || !reviewedLoaded || inconsistent ? <p>Reviewed document status unavailable.</p> : documents.length ? <p>Reviewed document: {documents.map(document => `version ${document.version} (${document.format.toUpperCase()})`).join(', ')}</p> : <p>{item.review ? 'Review comments submitted — no reviewed document attached.' : 'No reviewed document attached.'}</p>}
        </article>;
      })}
    </section>
    <h4>Outgoing grants</h4>{!currentView||!loaded?<p>History loading or unavailable.</p>:history.length===0?<p>No recorded grants; legacy delivery is unknown.</p>:<ul>{history.map(item=><li key={item.grant_id}>{item.version != null && <>Version {item.version} · </>}{item.mode==='automatic'?'Automatic':item.mode==='manual'?'Manual':'Document access'}{roundLabel(item)!=='Review round unavailable' && <> · {roundLabel(item)}</>} · Editor #{item.recipient_id} · {workflowStatusLabel(item.status)}{readableRecordedDate(item.created_at) && ` · ${readableRecordedDate(item.created_at)}`}{item.round_status==='unavailable'?' · round evidence unavailable; controlled access unavailable':''}{item.policy_status==='revoked'?' · policy revoked; controlled access unavailable':''}{item.invitation_revoked?' · invitation revoked; controlled access unavailable':''}{(item.invitation_id != null || item.actor_id != null || item.notification || item.email || item.sha256) && <details><summary>Recorded details</summary><p>{[item.invitation_id != null && `${item.invitation_kind || "Editor"} invitation #${item.invitation_id}`, item.actor_id != null && `EIC #${item.actor_id}`, item.notification && `notification ${item.notification}`, item.email && `email ${item.email}`, item.sha256 && `SHA-256 ${item.sha256}`].filter(Boolean).join(" · ")}</p></details>}{item.status==='access_granted'&&<button disabled={busy} onClick={()=>revoke(item.grant_id)}>Revoke access</button>}</li>)}</ul>}
    <h4>Incoming reviewed documents</h4>{!currentView||!reviewedLoaded?<p>Reviewed document history loading or unavailable.</p>:reviewed.length===0?<p>No reviewed documents recorded.</p>:<ul>{reviewed.map(item=><li key={item.artifact_id}>Round {item.review_round} · assignment #{item.assignment_id}{item.version != null && <> · version {item.version}</>} · {item.format.toUpperCase()}{item.byte_size != null && ` · ${item.byte_size} bytes`}{readableRecordedDate(item.created_at) && ` · ${readableRecordedDate(item.created_at)}`} · delivery not confirmed{item.sha256 && <details><summary>Recorded details</summary><p>SHA-256 {item.sha256}</p></details>} <button onClick={()=>{const expected=scope.current;const current=()=>active.current&&scope.current===expected;request(token,`/reviewed-documents/${item.artifact_id}/download`).then(r=>save(r,`reviewed-document.${item.format}`,current)).catch(e=>{if(current())setError(e.message)})}} >Download reviewed document</button></li>)}</ul>}
  </div></details>;
}
export function EditorReceivedDocuments({token}) {
 const [items,setItems]=useState([]),[error,setError]=useState(''),[owner,setOwner]=useState(null);const current=useRef(token),mounted=useRef(false);current.current=token;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 useEffect(()=>{let active=true;request(token,'/my').then(r=>r.json()).then(data=>{if(active){setItems(data);setOwner(token);setError('')}}).catch(e=>{if(active){setItems([]);setOwner(token);setError(e.message)}});return()=>{active=false}},[token]);
 if(owner!==token||(!items.length&&!error))return null;
 return <section aria-label="Received editorial documents"><h2>Received editorial documents</h2><ul>{items.map(item=><li key={item.grant_id}>{item.title} · version {item.version} · {item.format.toUpperCase()} · {item.mode==='automatic'?'Automatic':'Manual'} · {roundLabel(item)} · available <button onClick={()=>request(token,`/grants/${item.grant_id}/download`).then(r=>save(r,`editor-document.${item.format}`,()=>mounted.current&&current.current===token)).catch(e=>{if(mounted.current&&current.current===token)setError(e.message)})}>Download distributed document</button></li>)}</ul>{error&&<p role="alert">{displayError(error)}</p>}</section>;
}
export function ReviewerDocumentUpload({token,assignmentId,onSaved}) {
 const [file,setFile]=useState(null),[error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[available,setAvailable]=useState(false);const key=useRef(null);
 useEffect(()=>{let active=true;setAvailable(false);request(token,`/review-assignments/${assignmentId}/upload-availability`).then(r=>r.json()).then(data=>{if(active)setAvailable(data.available===true)}).catch(()=>{});return()=>{active=false}},[token,assignmentId]);
 const send=async e=>{e.preventDefault();if(!file)return;key.current ||= crypto.randomUUID().replaceAll('-','');setBusy(true);setError('');const body=new FormData();body.append('file',file);
  try{const r=await request(token,`/review-assignments/${assignmentId}/documents`,{method:'POST',headers:{'Idempotency-Key':key.current},body});const value=await r.json();setMessage(`Reviewed document saved: round ${value.review_round}, version ${value.version}.`);key.current=null;setFile(null);onSaved?.()}catch(e){setError(`${e.message}. Retry with the same file.`)}finally{setBusy(false)}};
 if(!available)return null;
 return <form onSubmit={send}><h4>Reviewed document (editorial only)</h4><label>Reviewed file <input type="file" accept=".pdf,.docx,.doc,.txt" onChange={e=>{setFile(e.target.files[0]||null);key.current=null}} /></label> <button disabled={busy||!file}>Upload reviewed document</button>{error&&<p role="alert">{displayError(error)}</p>}{message&&<p role="status">{message}</p>}</form>;
}

export function ReviewerDocumentHistory({token,assignmentId,revision=0}) {
 const [state,setState]=useState({owner:null,items:null,error:''});const scope=useRef({token,assignmentId,revision});const mounted=useRef(false);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 if(scope.current.token!==token||scope.current.assignmentId!==assignmentId||scope.current.revision!==revision)scope.current={token,assignmentId,revision};
 useEffect(()=>{let active=true;const owner=scope.current;setState({owner,items:null,error:''});
  request(token,`/review-assignments/${assignmentId}/documents`).then(r=>r.json()).then(items=>{
   if(!Array.isArray(items)||items.some(item=>item?.assignment_id!==assignmentId||typeof item.artifact_id!=='string'||!Number.isInteger(item.version)||!Number.isInteger(item.review_round)||!['pdf','docx','doc','txt'].includes(item.format)))throw new Error('Reviewed document history unavailable.');
   if(active&&scope.current===owner)setState({owner,items,error:''});
  }).catch(()=>{if(active&&scope.current===owner)setState({owner,items:null,error:'Reviewed document history unavailable.'})});
  return()=>{active=false};
 },[token,assignmentId,revision]);
 const download=async item=>{const owner=scope.current;try{
  const response=await request(token,`/review-assignments/${assignmentId}/documents/${item.artifact_id}/download`);
  await save(response,`reviewed-document.${item.format}`,()=>mounted.current&&scope.current===owner);
 }catch{if(mounted.current&&scope.current===owner)setState(previous=>({...previous,error:'Reviewed document download unavailable.'}))}};
 const current=state.owner===scope.current;const items=current?state.items:null;const error=current?state.error:'';
 return <section aria-label="Your reviewed documents"><h4>Your submitted reviewed documents</h4>
  {error&&<p role="status">{displayError(error)}</p>}
  {!items&&!error&&<p>Loading reviewed document history…</p>}
  {items?.length===0&&<p>No reviewed documents recorded for this assignment.</p>}
  {items?.length>0&&<ul>{items.map(item=><li key={item.artifact_id}>
   Reviewed document ({item.format.toUpperCase()}) · version {item.version} · Round {item.review_round} · assignment #{item.assignment_id}{readableRecordedDate(item.created_at) && ` · submitted ${readableRecordedDate(item.created_at)}`} · recorded; integrity verified on download
   <button type="button" onClick={()=>download(item)}>Download reviewed document, version {item.version}</button>
  </li>)}</ul>}
 </section>;
}
