import { EICDistribution } from "./DocumentDistribution";
import useManuscriptReturn from "./useManuscriptReturn";
import NotesPanel from "./NotesPanel";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, actionFailureMessage, submitAction } from "./api";
import NotificationBell from "./NotificationBell";
import FormattingPanel from "./FormattingPanel";
import BlindReviewPanel from "./BlindReviewPanel";
import EICReviewPolicyPanel from "./EICReviewPolicyPanel";
import ManuscriptProgress from "./ManuscriptProgress";
import GeneralCommentsPanel from "./GeneralCommentsPanel";
import AIPrescreeningPanel from "./AIPrescreeningPanel";
import "./EICDashboard.css";
import { eicPrompt } from "./participantPrompts";
import EICStageHistory from "./EICStageHistory";
import { InitialScreeningStageView, InitialEditorAssignmentView, InitialEditingReviewView, PeerReviewStageView, EICDecisionStageView, FinalEditorAssignmentView, FinalEditingReviewView } from "./EICStageViews";
import EICActivityHistory from "./EICActivityHistory";
import EICWorkQueue from "./EICWorkQueue";
import { PAGE_SIZE, statusLabel, statusValue, prepareManuscriptList } from "./eicManuscriptList";

const label = value => (value || "unknown").replaceAll("_", " ");
const stageNames = ['Submission', 'Initial Screening', 'Initial Editing', 'Peer Review', 'EIC Decision', 'Author Agreement', 'Final Editing', 'Formatting', 'Publication'];
const stageStateLabels = {completed:'Completed', current:'Current', pending:'Upcoming', unknown:'Unavailable'};
const stageDescriptions = {
  'Submission':'Manuscript information and the submitted document.',
  'Initial Screening':'Initial editorial screening and recorded decisions.',
  'Initial Editing':'Initial editor assignment and editing review.',
  'Peer Review':'Review assignments and current review progress.',
  'EIC Decision':'Editorial decision eligibility and actions.',
  'Author Agreement':'Author agreement status.',
  'Final Editing':'Final editor assignment and editing review.',
  'Formatting':'Formatting assignments and document review.',
  'Publication':'Recorded publication information.',
};

export default function EICDashboard({ user, token, registerManuscriptReturn }) {
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
  const [selectedStage, setSelectedStage] = useState(null);
  const handleProgress = useCallback(data => {
    if (!data || data.manuscript_id !== selectedRef.current) { setStageProgress(null); return; }
    const current = stageNames.includes(data.current_stage) ? data.current_stage : null;
    const previousCurrent = currentStageRef.current;
    currentStageRef.current = current;
    setStageProgress({current, stages:Array.isArray(data.stages) ? data.stages : []});
    setSelectedStage(previous => previous == null || previous === previousCurrent ? current : previous);
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
  const [unreadSummary, setUnreadSummary] = useState(null);
  const bellRef = useRef(null);
  const receiveUnread = useCallback(summary => setUnreadSummary(summary), []);
  const [busy, setBusy] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [detailDirty, setDetailDirty] = useState(false);
  const [progressRevision, setProgressRevision] = useState(0);
  const actionLock = useRef(false);
  const selectedRef = useRef(null);
  const requestVersion = useRef(0);
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
    if (!selected || (overview?.manuscript?.status !== 'formatting' && selectedStage !== 'Publication' && selectedStage !== 'Formatting')) return undefined;
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
      if (!busy && (!detailDirty || needsRefresh) && document.visibilityState === "visible") {
        refresh(selected).then(updated => { if (updated) { setError(""); setNeedsRefresh(false); } }).catch(e => { setNeedsRefresh(true); setError(`Refresh failed: ${e.message}`); });
      }
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [busy, detailDirty, needsRefresh, refresh, selected]);
  const open = async id => {
    if (selected !== null && selected !== id && detailDirty && !window.confirm('Discard unsaved editorial changes?')) return;
    selectedRef.current = id;
    const version = ++requestVersion.current;
    currentStageRef.current = null;
    setSelected(id); setOverview(null); setStageProgress(null); setSelectedStage(null); setFormattingGuidance(null); setDecision(""); setComments(""); setDetailDirty(false);
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
    if ((detailDirty || decision || comments || editor) && !window.confirm('Discard unsaved editorial changes?')) return false;
    selectedRef.current = null; requestVersion.current++; setSelected(null); setOverview(null); setDecision(''); setComments(''); setEditor(''); setDetailDirty(false); refresh(null).catch(e => setError(e.message));
    return true;
  };
  useManuscriptReturn(registerManuscriptReturn, returnToManuscripts);
  const {unique, counts, filtered} = prepareManuscriptList(listOwner === token ? manuscripts : [], search, filter, sortBy, sortDirection);
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pageItems = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  useEffect(() => { if (page > pageCount) setPage(pageCount); }, [page, pageCount]);
  const status = overview?.manuscript.status;
  const round = overview?.manuscript.review_round;
  const canDecide = Number.isInteger(round) && round > 0 && ["ready_for_peer_review", "revised"].includes(status) && overview?.review_progress?.can_decide === true && Array.isArray(overview?.decisions) && !overview.decisions.some(d => d.review_round === round);
  const approval = overview?.submissions.filter(s => s.status === "editor_approved") || [];
  const activeFinal = overview?.final_invitations.find(i => ["pending", "accepted"].includes(i.status));
  const latestFinal = overview?.final_workflow_submissions[0];
  const currentFormatting = formattingGuidance?.id === selected && formattingGuidance.revision === progressRevision && formattingGuidance.token === token ? formattingGuidance.data : null;
  const nextAction = eicPrompt(overview, needsRefresh || Boolean(error), currentFormatting);
  const chooseStage = stage => {
    if (!stageNames.includes(stage) || stage === selectedStage) return;
    if ((detailDirty || decision || comments || editor) && !window.confirm('Leave this stage? Unsaved changes may be lost.')) return;
    setSelectedStage(stage);
  };
  return <div className="eic-page">
    <header><div><h1>EIC Dashboard</h1><p>Welcome, {user.name}</p></div><div ref={bellRef}><NotificationBell token={token} onUnreadSummary={receiveUnread} onNavigate={notification => open(notification.manuscript_id)} /></div></header>
    {error && <p role="alert" className="eic-error">{error}</p>}{message && <p role="status">{message}</p>}
    <div className={`eic-grid${selected ? ' is-detail' : ''}`}>{!selected && <section data-sidebar-target="manuscripts" className="eic-listing"><h2>Manuscripts</h2>
      {listState === 'loading' || listOwner !== token && listState !== 'error' ? <p role="status">Loading manuscripts…</p> : listState === 'error' ? <div><p>Unable to load the manuscript list.</p><button type="button" onClick={() => refresh(null).then(() => setError('')).catch(e => setError(e.message))}>Retry manuscript list</button></div> : <>
      <p className="eic-list-summary">Accessible manuscripts: <strong>{unique.length}</strong> · Matching results: <strong>{filtered.length}</strong></p>
      <ul className="eic-status-counts" aria-label="Accessible manuscripts by status">{[...counts.keys()].sort((a,b)=>statusLabel(a).localeCompare(statusLabel(b))).map(s => <li key={s}>{statusLabel(s)}: <strong>{counts.get(s)}</strong></li>)}</ul>
      <div className="eic-list-controls"><label>Search <input value={search} onChange={e => {setSearch(e.target.value);setPage(1);}} placeholder="Title or ID" /></label>
      {search && <button type="button" onClick={() => {setSearch('');setPage(1);}}>Clear search</button>}
      <label>Status <select aria-label="Status" value={filter} onChange={e => {setFilter(e.target.value);setPage(1);}}><option value="">All statuses</option>{[...counts.keys()].sort((a,b)=>statusLabel(a).localeCompare(statusLabel(b))).map(s => <option key={s} value={s}>{statusLabel(s)} ({counts.get(s)})</option>)}</select></label>
      <label>Sort by <select value={sortBy} onChange={e => {setSortBy(e.target.value);setPage(1);}}><option value="id">Manuscript ID</option><option value="title">Title</option><option value="created_at">Created date</option><option value="status">Status</option></select></label>
      <button type="button" onClick={() => {setSortDirection(v=>v === 'asc' ? 'desc' : 'asc');setPage(1);}}>Order: {sortDirection === 'asc' ? 'Ascending ↑' : 'Descending ↓'}</button></div>
      {!filtered.length ? <p>{unique.length ? 'No manuscripts match the current search and filters.' : 'No accessible manuscripts are available.'}</p> : <table className="eic-list-table"><thead><tr><th>Manuscript</th><th>Status</th><th>Created</th></tr></thead><tbody>{pageItems.map(m => <tr key={m.manuscript_id}><td><button type="button" onClick={() => open(m.manuscript_id)}>#{m.manuscript_id} {m.title || 'Title unavailable'}</button></td><td>{statusLabel(statusValue(m))}</td><td>{Number.isFinite(Date.parse(m.created_at)) ? new Date(m.created_at).toLocaleDateString() : 'Unavailable'}</td></tr>)}</tbody></table>}
      <div className="eic-pagination"><label>Rows per page <select value={pageSize} onChange={e => {setPageSize(Number(e.target.value));setPage(1);}}>{[10, 25, 50].map(size => <option key={size} value={size}>{size}</option>)}</select></label><button type="button" disabled={currentPage === 1} onClick={() => setPage(currentPage-1)}>Previous</button><span>Page {filtered.length ? currentPage : 0} of {filtered.length ? pageCount : 0} · {filtered.length} results</span><button type="button" disabled={!filtered.length || currentPage === pageCount} onClick={() => setPage(currentPage+1)}>Next</button></div>
      </>}</section>}
    <main data-workspace={selected ? "selected" : undefined} onChangeCapture={() => { if (selected) setDetailDirty(true); }}>{!selected && <EICWorkQueue items={unique} state={listOwner !== token && listState !== 'error' ? 'loading' : listState} unread={unreadSummary?.token === token ? unreadSummary : null} onOpen={open} onRetry={() => refresh(null).then(() => setError('')).catch(e => setError(e.message))} onOpenNotifications={() => { const button=bellRef.current?.querySelector('.notification-bell'); if (button) { if (button.getAttribute('aria-expanded') !== 'true') button.click(); button.focus(); } }} />}{selected && <button type="button" className="manuscript-back" onClick={() => { if ((detailDirty || decision || comments || editor) && !window.confirm('Discard unsaved editorial changes?')) return; selectedRef.current = null; requestVersion.current++; setSelected(null); setOverview(null); setDecision(''); setComments(''); setEditor(''); setDetailDirty(false); refresh(null).catch(e => setError(e.message)); }}>Back to Manuscripts</button>}{selected && !overview && <p>Loading manuscript details…</p>}{overview && <>
      <section className="eic-manuscript-overview">
        <div className="eic-manuscript-heading">
          <div>
            <span className="eic-eyebrow">MANUSCRIPT OVERVIEW</span>
            <h2>{overview.manuscript.title?.trim() ? `#${selected} ${overview.manuscript.title}` : `Manuscript #${selected}`}</h2>
            <p>Review the manuscript information and current workflow progress.</p>
          </div>
          <span className={`eic-status-badge ${status}`}>
            {label(status)}
          </span>
        </div>

        <ManuscriptProgress showTitle={false} showNextAction={false} showRound={!(Number.isInteger(round) && round > 0)}
          key={`progress-${selected}-${progressRevision}`}
          manuscriptId={selected}
          token={token}
          onProgressChange={handleProgress}
        />
        <nav className="eic-stage-navigation" aria-label="Manuscript stages">
          {stageNames.map(name => {
            const entry = stageProgress?.stages.find(item => item.name === name);
            const state = Object.hasOwn(stageStateLabels, entry?.state) ? entry.state : 'unknown';
            return <button type="button" key={name} aria-current={stageProgress?.current === name ? 'step' : undefined} aria-pressed={selectedStage === name} onClick={() => chooseStage(name)}>{name} <small>{stageStateLabels[state]}</small></button>;
          })}
        </nav>
        {!stageProgress?.current && <p role="status">Current workflow stage is unavailable. Select a stage to browse its available information.</p>}

        <div className="eic-manuscript-meta">
          <p><strong>Review round:</strong> {Number.isInteger(round) && round > 0 ? round : 'Unavailable'}</p>
          <p><strong>Author:</strong> {overview.manuscript.author}</p>
          <div className="eic-abstract">
            <strong>Abstract</strong>
            <p>{overview.manuscript.abstract}</p>
          </div>
          <button
            type="button"
            onClick={() => download(`/manuscripts/${selected}/download`)}
          >
            Download submitted manuscript
          </button>
        </div>
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

      <EICDistribution key={`${token}-${selected}`} token={token} manuscriptId={selected} overview={overview} formatting={currentFormatting} onHistoryChange={receiveDistributionHistory} />

      <div className="eic-ai-section">
        <AIPrescreeningPanel
          key={`ai-prescreening-${selected}-${progressRevision}`}
          manuscriptId={selected}
          token={token}
          revision={progressRevision}
        />
      </div>
      <section className="eic-workflow" id="eic-current-actions">
        <div className="eic-workflow-heading">
          <div>
            <span className="eic-eyebrow">EDITORIAL WORKFLOW</span>
            <h3>{selectedStage || 'Stage information unavailable'}</h3>
            {selectedStage && <p>{stageDescriptions[selectedStage]}</p>}
            {selectedStage === stageProgress?.current && <p><strong>Next action:</strong> <span>{nextAction.text}</span></p>}
            {stageProgress?.current === 'Peer Review' && selectedStage === stageProgress?.current && nextAction.action === true && canDecide && !needsRefresh && !error && (
              <button type="button" onClick={() => chooseStage('EIC Decision')}>View editorial decision</button>
            )}
            {selectedStage && selectedStage !== stageProgress?.current && <p>Browsing this stage does not change the manuscript workflow.</p>}
          </div>
          <span className={`eic-status-badge ${status}`}>
            {label(status)}
          </span>
        </div>

        <div className="eic-workflow-grid">

          {stageProgress?.current === "Initial Screening" && selectedStage === "Initial Screening" && status === "submitted" && (
            <InitialScreeningStageView selected={selected} decision={decision} comments={comments}
              setDecision={setDecision} setComments={setComments} act={act} busy={busy} needsRefresh={needsRefresh} />
          )}

          {stageProgress?.current === "Initial Editing" && selectedStage === "Initial Editing" && status === "initial_scan_passed" && (
            <InitialEditorAssignmentView selected={selected} editor={editor} setEditor={setEditor} editors={editors} act={act} busy={busy} needsRefresh={needsRefresh} />
          )}

          {stageProgress?.current === "Initial Editing" && selectedStage === "Initial Editing" && status === "initial_editing" && approval.map(submission => (
            <InitialEditingReviewView key={submission.submission_id} submission={submission} decision={decision} comments={comments} setDecision={setDecision} setComments={setComments} act={act} busy={busy} needsRefresh={needsRefresh} />
          ))}

          {stageProgress?.current === "Peer Review" && selectedStage === "Peer Review" && ["ready_for_peer_review", "revised"].includes(status) && (
            <PeerReviewStageView overview={overview} />
          )}

          {stageProgress?.current === "Peer Review" && selectedStage === "EIC Decision" && canDecide && (
            <EICDecisionStageView selected={selected} round={round} decision={decision} comments={comments}
              setDecision={setDecision} setComments={setComments} act={act} busy={busy} needsRefresh={needsRefresh} />
          )}

          {stageProgress?.current === "Final Editing" && selectedStage === "Final Editing" && status === "final_editing" &&
            overview.author_agreement?.status === "accepted" && !activeFinal && (
              <FinalEditorAssignmentView selected={selected} editor={editor} setEditor={setEditor} editors={editors} act={act} busy={busy} needsRefresh={needsRefresh} />
          )}

          {stageProgress?.current === "Final Editing" && selectedStage === "Final Editing" && status === "final_editing" && latestFinal?.status === "pending_eic" && (
            <FinalEditingReviewView latestFinal={latestFinal} decision={decision} comments={comments} setDecision={setDecision} setComments={setComments} act={act} busy={busy} needsRefresh={needsRefresh} />
          )}

        </div>
      </section>

      {selectedStage === 'Submission' && <p>Submission details are available in the manuscript overview above.</p>}
      {selectedStage === 'EIC Decision' && !canDecide && <p>{overview.review_progress?.blocked_reason || 'A decision action is not currently available.'}</p>}
      <EICStageHistory stage={selectedStage} overview={overview} formatting={currentFormatting?.status === status ? currentFormatting : null} onDownload={download} />
      {selectedStage && selectedStage !== stageProgress?.current && <p>Detailed stage records may be available in Activity History below.</p>}
      <div hidden={stageProgress?.current !== 'Peer Review' || selectedStage !== 'Peer Review'}><section className="eic-reviewer-management">
        <div className="eic-section-heading">
          <div>
            <span className="eic-eyebrow">PEER REVIEW</span>
            <h3>Reviewer Management</h3>
            <p>Manage review policies, assignments and review progress.</p>
          </div>
        </div>

        {overview.split_review && (
          <section className="eic-action-card eic-split-review-card">
            <h4>Review Recommendations · Round {overview.split_review.review_round}</h4>
            <p>Completed assignment records in this round: {overview.assignments.filter(item => item.review_round === overview.split_review.review_round && item.status === "completed").length}.</p>
            <p>
              {overview.split_review.eligible_completed} eligible completed reviews:
              {" "}{overview.split_review.recommendations.join(", ") || "none yet"}.
            </p>
            <p>Completed assignments do not automatically qualify. Recommendation eligibility requires a completed current-round assignment, an accepted invitation, a reviewer account, a matching round file, and a submitted review with a valid recommendation. Invalidated assignments are excluded. If a reviewer has more than one qualifying review in the round, none of that reviewer's qualifying reviews are counted here.</p>
            <p>
              {({
                split: "Opposing accept and reject recommendations; an additional review may be requested.",
                aligned: "The first two recommendations are aligned.",
                ambiguous: "Revision recommendations need editorial interpretation; no automatic split classification.",
                insufficient: "Waiting for two eligible reviews."
              })[overview.split_review.classification]}
            </p>
            {overview.split_review.additional_assignments.map(a => (
              <p key={a.assignment_id}>
                Additional invitation: {a.invitation_status} · review: {a.review_status}
              </p>
            ))}
          </section>
        )}

        <EICReviewPolicyPanel key={`policy-${selected}`} manuscriptId={selected} token={token} invitationCount={overview.assignments.length} />
        <BlindReviewPanel
          key={selected}
          manuscriptId={selected}
          round={round}
          status={status}
          token={token}
          onChanged={() => refresh(selected)}
          splitReview={overview.split_review}
        />
      </section></div>

      <div hidden={stageProgress?.current !== 'Formatting' || selectedStage !== 'Formatting'}><section className="eic-formatting-section">
        <div className="eic-section-heading">
          <div>
            <span className="eic-eyebrow">PUBLICATION WORKFLOW</span>
            <h3>Formatting and Publication</h3>
            <p>Review formatted documents and manage publication.</p>
          </div>
        </div>
        <FormattingPanel
          key={`format-${selected}`}
          role="eic"
          token={token}
          manuscriptId={selected}
          canInvite={latestFinal?.status === "author_approved"}
          onChanged={() => refresh(selected)}
        />
      </section></div>
<details className="eic-history-collapsible">
        <summary>Workflow Comments</summary>
        <div className="eic-history-content">
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
    </>}</main></div></div>;
}
