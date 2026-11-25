import {workflowStageLabel, workflowStatusLabel} from './workflowStatus';
import {useEffect,useRef,useState} from 'react';
import {API_URL} from './api';
import {readableRecordedDate, recordedRole} from './recordedDisplay';

const known = value => value != null && String(value).trim() && !/^(unknown|unavailable|none)$/i.test(String(value).trim());

// Evidence is displayed as recorded; a binding or grant is not a delivery receipt.
export default function EICDocumentTimeline({token,manuscriptId,onDownload,revision=0}) {
 const scope=useRef({token,manuscriptId,revision});
 if(scope.current.token!==token||scope.current.manuscriptId!==manuscriptId||scope.current.revision!==revision)scope.current={token,manuscriptId,revision};
 const [state,setState]=useState({owner:null,items:null,unavailable:[],error:''});
 const [filters,setFilters]=useState({stage:'',round:'',artifact_type:'',direction:''});
 useEffect(()=>{setFilters({stage:'',round:'',artifact_type:'',direction:''})},[token,manuscriptId]);
 useEffect(()=>{const owner=scope.current;const controller=new AbortController();
  setState({owner,items:null,unavailable:[],error:''});
  fetch(`${API_URL}/eic/manuscripts/${manuscriptId}/document-timeline`,{headers:{Authorization:`Bearer ${token}`},cache:'no-store',signal:controller.signal})
   .then(async r=>{if(!r.ok)throw new Error('Document timeline unavailable.');return r.json()})
   .then(data=>{if(data.manuscript_id!==manuscriptId||!Array.isArray(data.events)||!Array.isArray(data.unavailable_sources))throw new Error('Document timeline unavailable.');if(!controller.signal.aborted&&scope.current===owner)setState({owner,items:data.events,unavailable:data.unavailable_sources,error:''})})
   .catch(()=>{if(!controller.signal.aborted&&scope.current===owner)setState({owner,items:null,unavailable:[],error:'Document timeline unavailable.'})});
  return()=>controller.abort();
 },[token,manuscriptId,revision]);
 const current=state.owner===scope.current;const items=current?state.items:null;const error=current?state.error:'';
 const round=item=>Number.isInteger(item.review_round)&&item.review_round>0?String(item.review_round):item.round_kind==='pre_review'?'pre-review':'unknown';
 const fields=[['stage','Stage'],['round','Round'],['artifact_type','Artifact type'],['direction','Direction']];
 const fieldValue=(item,key)=>key==='round'?round(item):item[key]||'unknown';
 const shown=(items||[]).filter(item=>fields.every(([key])=>!filters[key]||fieldValue(item,key)===filters[key]));
 const groups=[...new Set(shown.map(round))].sort((a,b)=>a==='pre-review'?-1:b==='pre-review'?1:a==='unknown'?1:b==='unknown'?-1:Number(a)-Number(b));
 return <section className="eic-document-timeline" aria-label="Generation document record"><h4>Generation document record</h4>
  <p>Records are grouped by round and direction, not ordered as a proven sequence. Bindings and grants do not establish download or external delivery. Unknown evidence is not inferred.</p>
  {error&&<p>{error}</p>}{!items&&!error&&<p>Loading document record…</p>}
  {current&&state.unavailable.length>0&&<p role="status">Some document history could not be loaded.</p>}
  {items&&<>{fields.map(([key,label])=><label key={key}>{label} <select aria-label={`Filter ${label.toLowerCase()}`} value={filters[key]} onChange={e=>setFilters({...filters,[key]:e.target.value})}><option value="">All</option>{[...new Set(items.map(item=>fieldValue(item,key)))].sort().map(value=><option key={value} value={value}>{key==='stage' ? workflowStageLabel(value) : value}</option>)}</select></label>)}
   {!shown.length?<p>No matching document records.</p>:groups.map(group=><section key={group}><h5>{group==='unknown'?'Other records':group==='pre-review'?'Pre-review':`Review round ${group}`}</h5>{['inbound','outbound','unknown'].map(direction=>{const rows=shown.filter(item=>round(item)===group&&(item.direction||'unknown')===direction);return rows.length>0&&<div key={direction}>{!(group==='unknown'&&direction==='unknown')&&<h6>{direction==='unknown'?'Other records':direction==='inbound'?'Inbound':'Outbound'}</h6>}<ul>{rows.map(item=>{
    const date=readableRecordedDate(item.timestamp);
    const evidence=[known(item.integrity)&&`Integrity: ${item.integrity}`,
      known(item.notification_evidence)&&`in-app notification state: ${item.notification_evidence==='not_requested'?'not requested':item.notification_evidence}`,
      known(item.email_evidence)&&`email: ${item.email_evidence==='not_requested'?'not requested':item.email_evidence}`,
      known(item.download_evidence)&&`download: ${item.download_evidence}`].filter(Boolean);
    return <li className="eic-document-record" key={item.id}><div className="eic-document-record-info">
      <strong>{workflowStageLabel(item.stage)} · {item.artifact_type}</strong>
      {(known(item.source)||known(item.destination))&&<p>{known(item.source)&&<>From: {recordedRole(item.source)}</>}{known(item.source)&&known(item.destination)&&' · '}{known(item.destination)&&<>To: {recordedRole(item.destination)}</>}</p>}
      {(date||known(item.status))&&<p>{date}{date&&known(item.status)&&' · '}{known(item.status)&&workflowStatusLabel(item.status)}</p>}
      {known(item.version) && <p>Version {item.version}</p>}
      {evidence.length>0&&<details><summary>Recorded evidence</summary><p>{evidence.join(' · ')}</p></details>}
    </div>{['reviewed_document','formatting','author_submission','final_editing'].includes(item.download?.kind)&&<button type="button" onClick={()=>onDownload(item.download)}>{item.download.kind==='formatting'?'Download formatting document':item.download.kind==='author_submission'?'Download submitted document':item.download.kind==='final_editing'?'Download final edit':'Download reviewed document'}</button>}</li>})}</ul></div>})}</section>)}
  </>}
 </section>;
}
