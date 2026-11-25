import {notificationTitle} from './notificationTitle';
import {recordedMessage} from './recordedDisplay';
import {useEffect, useRef, useState} from 'react';

function notificationDate(value) {
  if (typeof value !== 'string' || !value) return 'Date unavailable';
  const date=new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString();
}

export default function AuthorNotificationCenter({snapshot,token,onOpen,onBack}) {
  const [filter,setFilter]=useState('all');const [busy,setBusy]=useState(false);const [localError,setLocalError]=useState('');
  const epoch=useRef(0);
  useEffect(()=>{epoch.current+=1;return()=>{epoch.current+=1}},[token]);
  const current=snapshot?.token===token ? snapshot : null;
  const items=current?.state==='ready' ? current.items : [];
  const shown=items.filter(item=>filter==='all' || (filter==='read' ? item.is_read : !item.is_read));
  const mark=async id=>{const scope=epoch.current;setLocalError('');setBusy(true);try {if(!await current.markRead(id) && scope===epoch.current)setLocalError('Notification could not be updated.');} finally {if(scope===epoch.current)setBusy(false)}};
  const markAll=async()=>{const scope=epoch.current;setLocalError('');setBusy(true);try {for(const item of items.filter(item=>!item.is_read)){if(scope!==epoch.current)break;if(!await current.markRead(item.notification_id)){if(scope===epoch.current)setLocalError('Some notifications could not be updated.');break;}}} finally {if(scope===epoch.current)setBusy(false)}};
  return <section className="author-overview-card author-notification-center" aria-label="Notification center"><button type="button" className="author-text-action" onClick={onBack}>← Back</button><div className="section-header"><h2>Notifications</h2><button type="button" className="download-button" disabled={busy || !items.some(item=>!item.is_read)} onClick={markAll}>Mark all as read</button></div>
    <div className="author-notification-filters" aria-label="Notification filters">{[['all','All notifications'],['unread','Unread'],['read','Read']].map(([value,label])=><button key={value} type="button" className="download-button" aria-pressed={filter===value} onClick={()=>setFilter(value)}>{label}</button>)}</div>
    {(!current || current.state==='loading') && <p role="status">Loading notifications…</p>}
    {current?.state==='error' && <p role="alert">Notifications are unavailable. <button type="button" className="author-text-action" onClick={current.refresh}>Retry</button></p>}
    {localError && <p role="alert">{localError}</p>}
    {current?.state==='ready' && !shown.length && <p>No notifications in this view.</p>}
    {shown.length>0 && <ul className="author-notification-list">{shown.map(item=><li key={item.notification_id} className={item.is_read?'':'is-unread'}><div className="author-notification-content"><strong>{notificationTitle(item.notification_type)}</strong><p>{recordedMessage(item.message)}</p><small>{notificationDate(item.created_at)} · {item.is_read?'Read':'Unread'}</small></div><div className="author-notification-actions">{!item.is_read && <button type="button" className="download-button" disabled={busy} onClick={()=>mark(item.notification_id)}>Mark as read</button>}{item.manuscript_id && <button type="button" className="download-button" onClick={()=>onOpen(item)}>Open process</button>}</div></li>)}</ul>}
  </section>;
}
