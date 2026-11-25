import {displayError} from './displayError';
import './ManuscriptsListLayout.css';
import {workflowStageLabel, workflowStatusLabel} from './workflowStatus';
import useStageProjection, {StageProjectionNotice} from './useStageProjection';
import StageFilterControls, {StageFilterClear} from './StageFilterControls';
import RoleStatistics from './RoleStatistics';
import RoleOverview from "./RoleOverview";
import AuthorNotificationCenter from "./AuthorNotificationCenter";
import { EICDistribution } from "./DocumentDistribution";
import useManuscriptReturn from "./useManuscriptReturn";
import NotesPanel from "./NotesPanel";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, actionFailureMessage, submitAction } from "./api";
import NotificationBell from "./NotificationBell";
import ManuscriptProgress from "./ManuscriptProgress";
import GeneralCommentsPanel from "./GeneralCommentsPanel";
import AIPrescreeningPanel from "./AIPrescreeningPanel";
import "./EICDashboard.css";
import { eicPrompt } from "./participantPrompts";
import EICStageContent, { EICPeerReviewWorkspace, EICFormattingWorkspace } from "./EICStageContent";
import EICActivityHistory from "./EICActivityHistory";
import EICCandidateVerification from "./EICCandidateVerification";
import LifecycleAdministrationAccess from "./LifecycleAdministrationAccess";
import { PAGE_SIZE, statusLabel, statusValue, prepareManuscriptList } from "./eicManuscriptList";

const label = workflowStatusLabel;
const workspaceSessionKey = 'gsub-eic-workspace-v1';
const stageNames = ['Submission', 'Initial Screening', 'Initial Editing', 'Peer Review', 'EIC Decision', 'Author Agreement', 'Final Editing', 'Formatting', 'Proofing', 'Publication'];
const stageDescriptions = {
  'Submission':'Manuscript information and the submitted document.',
  'Initial Screening':'Initial editorial screening and recorded decisions.',
  'Initial Editing':'Initial editor assignment and editing review.',
  'Peer Review':'Review assignments and current review progress.',
  'EIC Decision':'Editorial decision eligibility and actions.',
  'Author Agreement':'Author agreement status.',
  'Final Editing':'Final editor assignment and editing review.',
  'Formatting':'Formatting assignments and document review.',
  'Proofing':'Review of the submitted formatted proof.',
  'Publication':'Recorded publication information.',
};

export default function EICDashboard({ user, token, accountControl, registerManuscriptReturn, section, onSectionChange }) {
  const [notificationSnapshot, setNotificationSnapshot] = useState(null);
  const receiveNotifications = useCallback(snapshot => setNotificationSnapshot(snapshot), []);
  const [manuscripts, setManuscripts] = useState([]);
  const [editors, setEditors] = useState([]);
  const [selected, setSelected] = useState(null);
  const [overviewResult, setOverviewResult] = useState(null);
  const overview = overviewResult?.token === token ? overviewResult.value : null;
  const setOverview = value => setOverviewResult(value === null ? null : {token, value});
  const activeToken = useRef(token);
  activeToken.current = token;
  const [stageProgress, setStageProgress] = useState(null);
  const currentStageRef = useRef(null);
  const restoreStageRef = useRef(null);
  const [selectedStage, setSelectedStage] = useState(null);
  const progressLocationRef = useRef(null);
  const workspaceLocationRef = useRef(null);
  const pendingStageNavigation = useRef(null);
  const revealWorkspace = useCallback(() => {
    const target = workspaceLocationRef.current;
    target?.focus({preventScroll: true});
    target?.scrollIntoView?.({block: 'start'});
  }, []);
  useEffect(() => {
    const pending = pendingStageNavigation.current;
    if (!pending) return;
    if (pending.manuscriptId !== selected) { pendingStageNavigation.current = null; return; }
    if (pending.stage === selectedStage) {
      pendingStageNavigation.current = null;
      revealWorkspace();
    }
  }, [selected, selectedStage, revealWorkspace]);
  const handleProgress = useCallback(data => {
    if (!data || data.manuscript_id !== selectedRef.current) { setStageProgress(null); return; }
    const current = stageNames.includes(data.current_stage) ? data.current_stage : null;
    const previousCurrent = currentStageRef.current;
    currentStageRef.current = current;
    setStageProgress({current, stages:Array.isArray(data.stages) ? data.stages : [], round:data.review_round, task:data.participant_task});
    const restored = restoreStageRef.current;
    if (restored?.manuscriptId === data.manuscript_id) restoreStageRef.current = null;
    setSelectedStage(previous => restored?.manuscriptId === data.manuscript_id && restored.stage !== null
      ? restored.stage : previous == null || previous === previousCurrent ? current : previous);
  }, []);
  const [formattingGuidance, setFormattingGuidance] = useState(null);
  const [distributionHistory, setDistributionHistory] = useState(null);
  const receiveDistributionHistory = useCallback((id, owner, records) => setDistributionHistory({id, owner, records}), []);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [listState, setListState] = useState('loading');
  const [listOwner, setListOwner] = useState(null);
  const [sortBy, setSortBy] = useState('id');
  const [sortDirection, setSortDirection] = useState('asc');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [decision, setDecision] = useState("");
  const [comments, setComments] = useState("");
  const [editor, setEditor] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [detailDirty, setDetailDirty] = useState(false);
  const [progressRevision, setProgressRevision] = useState(0);
  const actionLock = useRef(false);
  const selectedRef = useRef(null);
  const requestVersion = useRef(0);
  const restoredToken = useRef(null);
  const restoringWorkspace = useRef(false);
  const request = useCallback(async (path, options = {}) => {
    const response = await fetch(`${API_URL}${path}`, { ...options, headers: { Authorization: `Bearer ${token}`, ...options.headers } });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`);
    }
    return response.json();
  }, [token]);
  const refresh = useCallback(async (id = null) => {
    // A completed request for an older selection must never replace the current view.
    if (selectedRef.current !== id) return;
    const version = ++requestVersion.current;
    if (id === null) setListState('loading');
    try {
      const [list, people, details] = await Promise.all([
        request("/manuscripts/"), request("/eic/editors"),
        id ? request(`/eic/manuscripts/${id}/overview`) : Promise.resolve(null),
      ]);
      if (version !== requestVersion.current || selectedRef.current !== id || activeToken.current !== token) return false;
      if (!Array.isArray(list) || !Array.isArray(people) || (id && details?.manuscript?.manuscript_id !== id)) throw new Error('Invalid dashboard response.');
      setManuscripts(list); setEditors(people);
      setListOwner(token); setListState('ready');
      if (id) { setOverview(details); setProgressRevision(value => value + 1); }
      return true;
    } catch (e) {
      if (version !== requestVersion.current || selectedRef.current !== id || activeToken.current !== token) return false;
      if (id === null) setListState('error');
      throw e;
    }
  }, [request, token]);
  useEffect(() => {
    requestVersion.current += 1;
    currentStageRef.current = null;
    setOverviewResult(null); setStageProgress(null); setSelectedStage(null);
    setFormattingGuidance(null);
    setSearch(''); setFilter(''); setSortBy('id'); setSortDirection('asc'); setPage(1);
  }, [token]);
  useEffect(() => { refresh(selectedRef.current).catch(e => setError(e.message)); }, [refresh]);
  useEffect(() => {
    if (!selected || (overview?.manuscript?.status !== 'formatting' && !['Publication', 'Formatting', 'Proofing'].includes(selectedStage))) return undefined;
    const controller = new AbortController();
    const id = selected;
    const revision = progressRevision;
    setFormattingGuidance(null);
    request(`/formatting/manuscripts/${id}`, {signal: controller.signal})
      .then(data => { if (!controller.signal.aborted && data?.manuscript_id === id) setFormattingGuidance({id, revision, token, data}); })
      .catch(() => { if (!controller.signal.aborted) setFormattingGuidance(null); });
    return () => controller.abort();
  }, [selected, overview?.manuscript?.status, selectedStage, progressRevision, request, token]);
  useEffect(() => {
    const onFocus = () => {
      if (!busy && (!(detailDirty || decision || comments || editor) || needsRefresh) && document.visibilityState === "visible") {
        refresh(selected).then(updated => { if (updated) { setError(""); setNeedsRefresh(false); } }).catch(e => { setNeedsRefresh(true); setError(`Refresh failed: ${e.message}`); });
      }
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [busy, detailDirty, decision, comments, editor, needsRefresh, refresh, selected]);
  useEffect(() => {
    if (!selected || !(detailDirty || decision || comments || editor || busy)) return undefined;
    const onBeforeUnload = event => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [selected, detailDirty, decision, comments, editor, busy]);
  const open = async id => {
    if (busy || actionLock.current) return;
    if (selected !== null && selected !== id && (detailDirty || decision || comments || editor) && !window.confirm('Discard unsaved editorial changes?')) return;
    selectedRef.current = id;
    restoreStageRef.current = null;
    const version = ++requestVersion.current;
    currentStageRef.current = null;
    setSelected(id); setOverview(null); setStageProgress(null); setSelectedStage(null); setFormattingGuidance(null); setDecision(""); setComments(""); setEditor(""); setDetailDirty(false);
    if (!needsRefresh) { setError(""); setMessage(""); }
    try {
      const details = await request(`/eic/manuscripts/${id}/overview`);
      if (version === requestVersion.current && selectedRef.current === id && activeToken.current === token) {
        if (details?.manuscript?.manuscript_id !== id) throw new Error("Invalid manuscript response.");
        setOverview(details);
      }
    } catch (e) {
      if (version === requestVersion.current && selectedRef.current === id && activeToken.current === token) setError(e.message);
    }
  };
  useEffect(() => {
    if (!Number.isSafeInteger(user?.user_id) || user.user_id < 1 || restoredToken.current === token) return;
    restoredToken.current = token;
    try {
      const saved = JSON.parse(sessionStorage.getItem(workspaceSessionKey) || 'null');
      if (saved?.userId !== user.user_id || !Number.isSafeInteger(saved.manuscriptId) || saved.manuscriptId < 1 ||
          (saved.stage !== null && !stageNames.includes(saved.stage))) return;
      restoringWorkspace.current = true;
      open(saved.manuscriptId);
      restoreStageRef.current = {manuscriptId:saved.manuscriptId, stage:saved.stage};
      setSelectedStage(saved.stage);
    } catch { /* Storage is optional; normal list navigation remains available. */ }
  }, [token, user?.user_id]);
  useEffect(() => {
    if (!Number.isSafeInteger(user?.user_id) || user.user_id < 1 || restoredToken.current !== token) return;
    try {
      if (selected === null) {
        if (!restoringWorkspace.current) sessionStorage.removeItem(workspaceSessionKey);
      } else {
        restoringWorkspace.current = false;
        sessionStorage.setItem(workspaceSessionKey, JSON.stringify({userId:user.user_id, manuscriptId:selected, stage:selectedStage}));
      }
    } catch { /* Storage is optional; never block the workspace. */ }
  }, [selected, selectedStage, token, user?.user_id]);
  const act = async (path, payload) => {
    if (actionLock.current || needsRefresh) return;
    actionLock.current = true; setBusy(true); setError(""); setMessage("");
    try {
      await submitAction(`${API_URL}${path}`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    } catch (e) {
      setError(actionFailureMessage(e));
      if (!e.confirmedRejection) setNeedsRefresh(true);
      actionLock.current = false; setBusy(false);
      return;
    }
    // A successful HTTP response confirms the write even if a later GET fails.
    setMessage("Action completed."); setDecision(""); setComments(""); setEditor("");
    try {
      if (!await refresh(selectedRef.current)) throw new Error("Refresh superseded");
    } catch {
      setNeedsRefresh(true);
      setError("Action saved, but dashboard refresh failed. Displayed data may be stale. Return to this view; do not repeat the action.");
    } finally { actionLock.current = false; setBusy(false); }
  };
  const download = async path => {
    try {
      const response = await fetch(`${API_URL}${path}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Download failed (${response.status})`); }
      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") || "";
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || "manuscript";
      const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url);
    } catch (e) { setError(e.message); }
  };
  const returnToManuscripts = () => {
    if (busy || actionLock.current) return false;
    if ((detailDirty || decision || comments || editor) && !window.confirm('Discard unsaved editorial changes?')) return false;
    selectedRef.current = null; requestVersion.current++; setSelected(null); setOverview(null); setDecision(''); setComments(''); setEditor(''); setDetailDirty(false); refresh(null).catch(e => setError(e.message));
    return true;
  };
  useManuscriptReturn(registerManuscriptReturn, returnToManuscripts);
  const stageProjection = useStageProjection(listOwner === token ? manuscripts : [], token, filter);
  const {unique, filtered} = prepareManuscriptList(stageProjection.items, search, filter, sortBy, sortDirection);
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pageItems = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  useEffect(() => { if (page > pageCount) setPage(pageCount); }, [page, pageCount]);
  const status = overview?.manuscript.status;
  const round = overview?.manuscript.review_round;
  const displayedRound = Number.isInteger(round) && round > 0 ? round :
    Number.isInteger(stageProgress?.round) && stageProgress.round > 0 ? stageProgress.round : 'Unavailable';
  const roundConflict = Number.isInteger(round) && round > 0 && Number.isInteger(stageProgress?.round) && stageProgress.round !== round;
  const decisionRoundUnverified = ['ready_for_peer_review', 'revised'].includes(status) && (!Number.isInteger(round) || round < 1 || stageProgress?.round !== round);
  const canDecide = Number.isInteger(round) && round > 0 && stageProgress?.round === round && ["ready_for_peer_review", "revised"].includes(status) && overview?.review_progress?.can_decide === true && Array.isArray(overview?.decisions) && !overview.decisions.some(d => d.review_round === round);
  const approval = overview?.submissions.filter(s => s.status === "editor_approved") || [];
  const hasWorkflowComments = Boolean(overview && (
    overview.scans.some(item => item.comments) ||
    overview.submissions.some(item => item.comments || item.author_comments || item.editor_comments || item.eic_comments) ||
    overview.confirmations.some(item => item.comments) || overview.decisions.some(item => item.comments) ||
    overview.final_submissions.some(item => item.comments)
  ));
  const activeFinal = overview?.final_invitations.find(i => ["pending", "accepted"].includes(i.status));
  const latestFinal = overview?.final_workflow_submissions[0];
  const currentFormatting = formattingGuidance?.id === selected && formattingGuidance.revision === progressRevision && formattingGuidance.token === token ? formattingGuidance.data : null;
  const nextAction = eicPrompt(overview, needsRefresh || Boolean(error), currentFormatting);
  const primaryTask = stageProgress?.task;
  const taskMessage = !needsRefresh && !error && primaryTask?.relevant_stage === stageProgress?.current &&
    ['action_required', 'waiting', 'no_action'].includes(primaryTask?.task_state) &&
    typeof primaryTask.task_message === 'string' && primaryTask.task_message.trim()
    ? primaryTask.task_message : nextAction.text;
  const selectedTaskMessage = needsRefresh || error ? nextAction.text
    : roundConflict || decisionRoundUnverified ? 'Review-round information is unavailable or inconsistent. Refresh before acting.'
    : selectedStage && selectedStage !== stageProgress?.current
      ? selectedStage === 'EIC Decision' && stageProgress?.current === 'Peer Review' && canDecide
        ? 'Review the editorial decision controls for the current round.'
        : 'This stage is being viewed for context; the current workflow task is unchanged.'
      : taskMessage;
  const chooseStage = stage => {
    if (!stageNames.includes(stage) || busy || actionLock.current) return;
    if (stage === selectedStage) { revealWorkspace(); return; }
    if ((detailDirty || decision || comments || editor) && !window.confirm('Leave this stage? Unsaved changes may be lost.')) return;
    restoreStageRef.current = null;
    setDecision(''); setComments(''); setEditor('');
    pendingStageNavigation.current = {stage, manuscriptId: selected};
    setSelectedStage(stage);
  };
  return <div className="eic-page">
    <header><div><h1>EIC Dashboard</h1><p>Welcome, {user.name}</p></div><div className="dashboard-utilities"><NotificationBell token={token} onNavigate={notification => { onSectionChange?.("manuscripts"); open(notification.manuscript_id); }} onViewAll={onSectionChange ? () => { if (returnToManuscripts() !== false) onSectionChange("notifications"); } : undefined} onAuthorSnapshot={onSectionChange ? receiveNotifications : undefined} />{accountControl}</div></header>
    {error && <p role="alert" className="eic-error">{displayError(error)}</p>}{message && <p role="status">{message}</p>}
    <div hidden={section === "notifications"}><LifecycleAdministrationAccess key={`lifecycle-${token}`} token={token} currentUserId={user.user_id} /></div>
    {section === 'dashboard' && <RoleOverview label="EIC" items={unique} loading={listState === 'loading' || listOwner !== token} error={listState === 'error'} onNavigate={onSectionChange} onOpen={item => { onSectionChange('manuscripts'); open(item.manuscript_id); }} />}
    {section === 'notifications' && <AuthorNotificationCenter snapshot={notificationSnapshot} token={token} onOpen={item => { onSectionChange('manuscripts'); open(item.manuscript_id); }} onBack={() => onSectionChange('dashboard')} />}
    <div hidden={Boolean(section && section !== 'manuscripts')}>
    <div className={`eic-grid${selected ? ' is-detail' : ''}`}>{!selected && <section data-sidebar-target="manuscripts" className="eic-listing"><div className="manuscripts-list-layout"><div className="manuscripts-list-content"><h2>Manuscripts</h2>
      {listState === 'loading' || listOwner !== token && listState !== 'error' ? <p role="status">Loading manuscripts…</p> : listState === 'error' ? <div><p>Unable to load the manuscript list.</p><button type="button" onClick={() => refresh(null).then(() => setError('')).catch(e => setError(e.message))}>Retry manuscript list</button></div> : <>
      <div className="eic-list-controls"><label>Search <input value={search} onChange={e => {setSearch(e.target.value);setPage(1);}} placeholder="Title or ID" /></label>
      {search && <button type="button" onClick={() => {setSearch('');setPage(1);}}>Clear search</button>}
      <StageProjectionNotice projection={stageProjection} /><StageFilterControls value={filter} onChange={value => {setFilter(value);setPage(1);}} items={unique} />
      <label>Sort by <select value={sortBy} onChange={e => {setSortBy(e.target.value);setPage(1);}}><option value="id">Manuscript ID</option><option value="title">Title</option><option value="created_at">Created date</option><option value="status">Status</option></select></label>
      <button type="button" onClick={() => {setSortDirection(v=>v === 'asc' ? 'desc' : 'asc');setPage(1);}}>Order: {sortDirection === 'asc' ? 'Ascending ↑' : 'Descending ↓'}</button><StageFilterClear onClear={() => {setSearch('');setFilter('');setSortBy('id');setSortDirection('asc');setPage(1);}} /></div>
      {stageProjection.loading ? null : !filtered.length && stageProjection.unavailable ? <p>Matching manuscripts cannot be determined until stage information is available.</p> : !filtered.length ? <p>{unique.length ? 'No manuscripts match the current search and filters.' : 'No accessible manuscripts are available.'}</p> : <div className="eic-table-scroll"><table className="eic-list-table"><thead><tr><th scope="col">ID</th><th scope="col">Manuscript</th><th scope="col">Status</th><th scope="col">Created</th></tr></thead><tbody>{pageItems.map(m => <tr key={m.manuscript_id}><td>#{m.manuscript_id}</td><td><button type="button" aria-label={`#${m.manuscript_id} ${m.title || 'Title unavailable'}`} onClick={() => open(m.manuscript_id)}>{m.title || 'Title unavailable'}</button></td><td>{statusLabel(statusValue(m))}</td><td>{Number.isFinite(Date.parse(m.created_at)) ? new Date(m.created_at).toLocaleDateString() : 'Unavailable'}</td></tr>)}</tbody></table></div>}
      {stageProjection.unavailable && <p>Result counts exclude manuscripts whose stages could not be verified.</p>}<div className="eic-pagination"><label>Rows per page <select value={pageSize} onChange={e => {setPageSize(Number(e.target.value));setPage(1);}}>{[10, 25, 50].map(size => <option key={size} value={size}>{size}</option>)}</select></label><button type="button" disabled={currentPage === 1} onClick={() => setPage(currentPage-1)}>Previous</button>{!stageProjection.loading && !stageProjection.unavailable && <><span aria-live="polite">Page {filtered.length ? currentPage : 0} of {filtered.length ? pageCount : 0} · {filtered.length} results</span><span aria-live="polite">{filtered.length ? `Showing ${(currentPage - 1) * pageSize + 1}–${Math.min(currentPage * pageSize, filtered.length)} of ${filtered.length} matching manuscripts` : "Showing 0 of 0 matching manuscripts"}</span></>}<button type="button" disabled={!filtered.length || currentPage === pageCount} onClick={() => setPage(currentPage+1)}>Next</button></div>
      </>}</div><aside className="manuscripts-list-sidebar" aria-label="Manuscript statistics"><RoleStatistics items={unique} loading={listState === 'loading' || listOwner !== token} error={listState === 'error'} /></aside></div></section>}
    {selected && <main className="manuscripts-list-layout" data-workspace={selected ? "selected" : undefined} onChangeCapture={event => { if (selected && !event.target.closest('.eic-workflow')) setDetailDirty(true); }}><aside className="manuscripts-list-sidebar" aria-label="Manuscript statistics"><RoleStatistics items={unique} loading={listState === 'loading' || listOwner !== token} error={listState === 'error'} /></aside><div className="manuscripts-list-content">{selected && <button type="button" className="manuscript-back" onClick={() => { if (busy || actionLock.current) return; if ((detailDirty || decision || comments || editor) && !window.confirm('Discard unsaved editorial changes?')) return; selectedRef.current = null; requestVersion.current++; setSelected(null); setOverview(null); setDecision(''); setComments(''); setEditor(''); setDetailDirty(false); refresh(null).catch(e => setError(e.message)); }}>Back to manuscripts</button>}{selected && !overview && <p>Loading manuscript details…</p>}{overview && <>
      <section className="eic-manuscript-overview">
        <div className="eic-manuscript-heading">
          <div>
            <span className="eic-eyebrow">MANUSCRIPT OVERVIEW</span>
            <h2>{overview.manuscript.title?.trim() || `Manuscript #${selected}`}</h2>
            {overview.manuscript.title?.trim() && <p className="eic-manuscript-id">Manuscript #{selected}</p>}
          </div>
          <span className={`eic-status-badge ${status}`}>
            {label(status)}
          </span>
        </div>

        <section className="eic-abstract" aria-label="Manuscript Abstract">
          <h3>Manuscript Abstract</h3>
          <p>{overview.manuscript.abstract}</p>
        </section>
      </section>

      <details className="eic-context-panel">
        <summary>Private Notes</summary>
        <div className="eic-context-content">
          <NotesPanel key={`notes-${selected}`} manuscriptId={selected} token={token} />
        </div>
      </details>

      <details className="eic-context-panel">
        <summary>Comments (Staff Shared)</summary>
        <div className="eic-context-content">
          <GeneralCommentsPanel key={`comments-${selected}`} manuscriptId={selected} token={token} />
        </div>
      </details>

      <section className="eic-progress-content">
        <div ref={progressLocationRef} tabIndex={-1} aria-label="Manuscript Progress navigation">
        <ManuscriptProgress showTitle={false} showNextAction={false} showRound={false}
          key={`progress-${selected}-${progressRevision}`}
          manuscriptId={selected}
          token={token}
          onProgressChange={handleProgress}
          onBrowseStage={chooseStage}
          selectedStage={selectedStage}
        />
        </div>
        {!stageProgress?.current && <p role="status">Current workflow stage is unavailable. Select a stage to browse its available information.</p>}
        <div className="eic-manuscript-meta">
          <p><strong>Review round:</strong> {displayedRound}</p>
          <p><strong>Author:</strong> {overview.manuscript.author}</p>
          <button
            type="button"
            onClick={() => download(`/manuscripts/${selected}/download`)}
          >
            Download submitted manuscript
          </button>
        </div>
      </section>

      <EICCandidateVerification key={`candidate-${token}-${selected}`} manuscriptId={selected} token={token} />

      <EICDistribution key={`${token}-${selected}`} token={token} manuscriptId={selected} overview={overview} formatting={currentFormatting} revision={progressRevision} onHistoryChange={receiveDistributionHistory} />

      <div className="eic-ai-section">
        <AIPrescreeningPanel
          key={`ai-prescreening-${selected}-${progressRevision}`}
          manuscriptId={selected}
          token={token}
          revision={progressRevision}
        />
      </div>
      <section className="eic-workflow" id="eic-current-actions" ref={workspaceLocationRef} tabIndex={-1}>
        <div className="eic-workflow-heading">
          <div>
            <span className="eic-eyebrow">EDITORIAL WORKFLOW</span>
            <h3>{selectedStage ? workflowStageLabel(selectedStage) : 'Stage information unavailable'}</h3>
            {selectedStage && <p>{stageDescriptions[selectedStage]}</p>}
            <div className="eic-stage-next-action" aria-live="polite">
              <h4>Next action:</h4>
              <p>{stageProgress?.current ? selectedTaskMessage : 'Unavailable until the current stage is known.'}</p>
              {!needsRefresh && !error && !busy && !roundConflict && !decisionRoundUnverified && selectedStage === stageProgress?.current && primaryTask?.task_state === 'action_required' && primaryTask.relevant_stage === selectedStage && (
                (selectedStage === 'Initial Screening' && primaryTask.action_label === 'View initial screening' && primaryTask.permitted_action_target === `#eic-initial-screening-${selected}`) ||
                (selectedStage === 'Initial Editing' && primaryTask.action_label === 'View initial editor assignment' && primaryTask.permitted_action_target === `#eic-initial-assignment-${selected}`) ||
                (selectedStage === 'Peer Review' && ['ready_for_peer_review', 'revised'].includes(status) && overview?.review_progress?.active_assignments === 0 && primaryTask.action_label === 'View review policy' && primaryTask.permitted_action_target === `#eic-reviewer-management-${selected}`) ||
                (selectedStage === 'Peer Review' && ['ready_for_peer_review', 'revised'].includes(status) && overview?.review_progress?.active_assignments === 0 && primaryTask.action_label === 'View reviewer invitations' && primaryTask.permitted_action_target === `#eic-reviewer-management-${selected}`) ||
                (selectedStage === 'Initial Editing' && status === 'initial_editing' && approval.length > 0 && primaryTask.action_label === 'View initial editing review' && primaryTask.permitted_action_target === `#eic-initial-review-${selected}`)
              ) && <a href={primaryTask.permitted_action_target}>{primaryTask.action_label}</a>}
            </div>
            {stageProgress?.current === 'Peer Review' && selectedStage === stageProgress?.current && canDecide && !needsRefresh && !error && !busy &&
              primaryTask?.task_state === 'action_required' && primaryTask.relevant_stage === 'Peer Review' &&
              primaryTask.action_label === 'View editorial decision' && primaryTask.permitted_action_target === `#eic-decision-${selected}` && (
              <a href={primaryTask.permitted_action_target} onClick={event => {
                event.preventDefault();
                chooseStage('EIC Decision');
              }}>View editorial decision</a>
            )}
            {stageProgress?.current === 'Peer Review' && selectedStage === stageProgress?.current && nextAction.action === true && canDecide && !needsRefresh && !error && !busy && !primaryTask?.permitted_action_target && (
              <button type="button" onClick={() => chooseStage('EIC Decision')}>View editorial decision</button>
            )}
            {selectedStage && selectedStage !== stageProgress?.current && <p>Browsing this stage does not change the manuscript workflow.</p>}
          </div>
          <span className={`eic-status-badge ${status}`}>
            {label(status)}
          </span>
        </div>

        <EICStageContent stage={selectedStage} context={{
          overview, formatting:currentFormatting, status, currentStage:stageProgress?.current,
          selected, round, decision, comments, editor, editors, setDecision, setComments,
          setEditor, act, busy, needsRefresh, approval, canDecide, activeFinal, latestFinal, download,
        }} />
      </section>

      <EICPeerReviewWorkspace currentStage={stageProgress?.current} selectedStage={selectedStage} overview={overview} selected={selected} round={round} status={status} token={token} refresh={refresh} />
      <EICFormattingWorkspace currentStage={stageProgress?.current} selectedStage={selectedStage} selected={selected} token={token} latestFinal={latestFinal} refresh={refresh} />
<details className="eic-history-collapsible">
        <summary>Workflow Comments</summary>
        <div className="eic-history-content">
          {!hasWorkflowComments && <p>No workflow comments are available.</p>}
          {overview.scans.map((item, i) => item.comments && <p key={`scan-${i}`}>Screening: {item.comments}</p>)}
          {overview.submissions.map(item => <div key={`submission-${item.submission_id}`}>
            {item.comments && <p>Initial edit #{item.submission_id}: {item.comments}</p>}
            {item.author_comments && <p>Author: {item.author_comments}</p>}
            {item.editor_comments && <p>Editor: {item.editor_comments}</p>}
            {item.eic_comments && <p>EIC: {item.eic_comments}</p>}
          </div>)}
          {overview.confirmations.map((item, i) => item.comments && <p key={`confirmation-${i}`}>Confirmation #{item.submission_id}: {item.comments}</p>)}
          {overview.decisions.map((item, i) => item.comments && <p key={`decision-${i}`}>Decision round {item.review_round}: {item.comments}</p>)}
          {overview.final_submissions.map(item => item.comments && <p key={`final-${item.submission_id}`}>Final edit #{item.submission_id}: {item.comments}</p>)}
        </div>
      </details>
<details className="eic-history-collapsible">
        <summary>Reviewer Feedback</summary>
        <div className="eic-history-content">
          {overview.assignments.some(item => item.review) ? overview.assignments.map(item => item.review && <div key={`review-${item.assignment_id}`}><p>Review round {item.review_round} · Recommendation: {label(item.review.recommendation)}</p>{item.review.comments && <p>{item.review.comments}</p>}</div>) : <p>No reviewer feedback is available.</p>}
        </div>
      </details>
      <EICActivityHistory overview={overview} formatting={currentFormatting} distribution={distributionHistory?.id === selected && distributionHistory.owner === token ? distributionHistory.records : null} onDownload={download} />
    </>}</div></main>}</div></div></div>;
}
