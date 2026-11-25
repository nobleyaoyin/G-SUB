import {displayError} from './displayError';
import {useEffect,useRef,useState} from 'react';
import {API_URL} from './api';
import './AuthorGenerationHistory.css';

function recordedTime(value) {
 if (typeof value !== 'string' || !value.trim()) return 'Time unavailable';
 const validIso = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?$/i.test(value);
 if (!validIso || Number.isNaN(Date.parse(value))) return 'Time unavailable';
 if (!/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return `${value.replace('T', ' ')} (timezone unavailable)`;
 return new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(new Date(value)) + ' (local time)';
}


export default function AuthorGenerationHistory({token,manuscriptId,revision=0}) {
 const scope=useRef({token,manuscriptId,revision});const mounted=useRef(false);
 if(scope.current.token!==token||scope.current.manuscriptId!==manuscriptId||scope.current.revision!==revision)scope.current={token,manuscriptId,revision};
 const [state,setState]=useState({owner:null,entries:null,error:'',notice:'',unavailable:[]});
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 useEffect(()=>{const owner=scope.current;const controller=new AbortController();setState({owner,entries:null,error:'',notice:'',unavailable:[]});
  fetch(`${API_URL}/manuscripts/${manuscriptId}/generation-history`,{headers:{Authorization:`Bearer ${token}`},cache:'no-store',signal:controller.signal})
   .then(async r=>{if(!r.ok)throw new Error();return r.json()})
   .then(data=>{if(data.manuscript_id!==manuscriptId||!Array.isArray(data.entries)||!Array.isArray(data.unavailable_sources))throw new Error();if(!controller.signal.aborted&&scope.current===owner)setState({owner,entries:data.entries,error:'',notice:data.historical_notice,unavailable:data.unavailable_sources})})
   .catch(()=>{if(!controller.signal.aborted&&scope.current===owner)setState({owner,entries:null,error:'Generation history unavailable.',notice:'',unavailable:[]})});
  return()=>controller.abort();
 },[token,manuscriptId,revision]);
 const current=state.owner===scope.current;const entries=current?state.entries:null;const error=current?state.error:'';
 const download=async item=>{const owner=scope.current;try{
  const kind=item.download.kind === 'author_submission' ? 'submissions' : item.download.kind === 'approved_final' ? 'final-editing' : 'formatting';
  const r=await fetch(`${API_URL}/manuscripts/${manuscriptId}/generation-history/${kind}/${encodeURIComponent(item.download.id)}/download`,{headers:{Authorization:`Bearer ${token}`},cache:'no-store'});
  if(!r.ok)throw new Error();const blob=await r.blob();if(!mounted.current||scope.current!==owner)return;
  const content=r.headers.get('content-type')||'';const ext={'application/pdf':'.pdf','text/plain':'.txt','application/msword':'.doc','application/vnd.openxmlformats-officedocument.wordprocessingml.document':'.docx'}[content]||'';
  const url=URL.createObjectURL(blob);try{const a=document.createElement('a');a.href=url;a.download=`approved-document${ext}`;a.click()}finally{setTimeout(()=>URL.revokeObjectURL(url),1000)}
 }catch{if(mounted.current&&scope.current===owner)setState(previous=>({...previous,error:'Document download unavailable.'}))}};
 const sections=[['submissions','Manuscript submissions'],['generations','Review generations'],['outputs','Final outputs']];
 const renderItems=list=><ul className="author-history-list">{list.map(item=><li className="author-history-item" key={item.id}>
  <div className="author-history-heading"><strong>{item.title}</strong><span className="author-history-status">{item.status || 'Status unavailable'}</span></div>
  <p className="author-history-metadata">{item.stage || 'Stage unavailable'} · {Number.isInteger(item.review_round)?`Round ${item.review_round}`:'Round unavailable or not applicable'} · Version {item.version??'unavailable'} · Format {['pdf','docx','doc','txt'].includes(item.file_format)?item.file_format.toUpperCase():'unavailable'}</p>
  <p className="author-history-recorded">Recorded: {recordedTime(item.recorded_at)}</p>
  {((['approved_formatting','approved_final'].includes(item.download?.kind)&&Number.isInteger(item.download.id))||(item.download?.kind==='author_submission'&&typeof item.download.id==='string'&&/^[0-9a-f]{32}$/.test(item.download.id)))&&<button className="author-history-download" type="button" onClick={()=>download(item)}>{item.download.kind==='author_submission'?'Download submitted document':item.download.kind==='approved_final'?'Download approved final edit':'Download approved document'}</button>}
 </li>)}</ul>;
 return <details className="workspace-context"><summary>Generation history</summary><section aria-label="Author generation history">
  {error&&<p role="alert">{displayError(error)}</p>}{!entries&&!error&&<p role="status">Loading generation history…</p>}
  {entries&&<>{state.notice && state.notice !== 'Historical release status unavailable. Artifacts with unknown release are not listed.' && <p>{state.notice}</p>}{state.unavailable.length>0&&<p>Some history could not be loaded.</p>}
   {sections.map(([key,label])=>{const list=entries.filter(item=>item.section===key);const rounds=[...new Set(list.map(item=>Number.isInteger(item.review_round)?item.review_round:null))].sort((a,b)=>a===null?1:b===null?-1:a-b);return <section key={key}><h4>{label}</h4>{!list.length?<p>No verified records available.</p>:key==='generations'?rounds.map(round=><div key={round??'unknown'}><h5>{round===null?'Round unavailable or not applicable':`Review round ${round}`}</h5>{renderItems(list.filter(item=>(item.review_round??null)===round))}</div>):renderItems(list)}</section>})}
  </>}
 </section></details>;
}
