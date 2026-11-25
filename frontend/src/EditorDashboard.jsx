import {displayError} from './displayError';
import StatusBadge from './StatusBadge';
import './ManuscriptsListLayout.css';
import {workflowStatusLabel} from './workflowStatus';
import EditorAssignmentStatistics from './EditorAssignmentStatistics';
import {pendingEditorInvitations} from './editorInvitationList';
import useStageProjection, {StageProjectionNotice} from './useStageProjection';
import RoleListControls, { selectRoleItems } from "./RoleListControls";
import RoleOverview from "./RoleOverview";
import AuthorNotificationCenter from "./AuthorNotificationCenter";
import ManuscriptTimeline from "./ManuscriptTimeline";
import { EditorReceivedDocuments } from "./DocumentDistribution";
import useManuscriptReturn from "./useManuscriptReturn";
import NotesPanel from "./NotesPanel";
import EmailDemoPanel from "./EmailDemoPanel";

import { useCallback, useEffect, useRef, useState } from "react";
import "./EditorDashboard.css";
import NotificationBell from "./NotificationBell";
import ReviewerInvitationPanel from "./ReviewerInvitationPanel";
import InitialEditingPanel from "./InitialEditingPanel";
import FinalEditingPanel from "./FinalEditingPanel";
import FormattingPanel from "./FormattingPanel";
import useReturnRefresh from "./useReturnRefresh";
import ManuscriptProgress from "./ManuscriptProgress";
import GeneralCommentsPanel from "./GeneralCommentsPanel";
import { PRODUCT_DISPLAY_NAME, PRODUCT_SYSTEM_NAME } from "./branding";

import { API_URL } from "./api";

function EditorDashboard({ user, token, accountControl, registerManuscriptReturn, section, onSectionChange }) {
  const [listSearch, setListSearch] = useState("");
  const [listStatus, setListStatus] = useState("");
  const [listSort, setListSort] = useState("recent");
  const [notificationSnapshot, setNotificationSnapshot] = useState(null);
  const receiveNotifications = useCallback(snapshot => setNotificationSnapshot(snapshot), []);
  const [manuscripts, setManuscripts] = useState([]);
  const [formattingAssignments, setFormattingAssignments] = useState([]);
  const [pendingInvitations, setPendingInvitations] = useState([]);
  const [invitationWarning, setInvitationWarning] = useState(false);
  const [summary, setSummary] = useState(null);
  const [dashboardOwner, setDashboardOwner] = useState(null);
  const dashboardRequest = useRef(0);
  const historyRequest = useRef(0);
  const context = useRef({ token, expandedId: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const [expandedId, setExpandedId] = useState(null);
  if (context.current.token !== token) {
    context.current = { token, expandedId: null };
    dashboardRequest.current += 1;
    historyRequest.current += 1;
  } else {
    context.current.expandedId = expandedId;
  }
  const [detailDirty, setDetailDirty] = useState(false);
  const [formattingDirty, setFormattingDirty] = useState(false);
  const [onlineDraftsDirty, setOnlineDraftsDirty] = useState({});
  const onlineDirty = Object.values(onlineDraftsDirty).some(Boolean);
  const onOnlineDirtyChange = useCallback((key, dirty) => setOnlineDraftsDirty(previous => ({...previous, [key]: dirty})), []);
  const [decisions, setDecisions] = useState({});
  const [reviewHistory, setReviewHistory] = useState({});
  const [historyLoadingId, setHistoryLoadingId] = useState(null);
  const [actionLoadingId, setActionLoadingId] = useState(null);
  const [progressRevision, setProgressRevision] = useState(0);

  const actionLock = useRef(false);

  // Read API response and handle errors
  const readResponse = async (response, fallback) => {
    const contentType =
      response.headers.get("content-type") || "";

    let data;

    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      const text = await response.text();
      data = { detail: text || fallback };
    }

    if (!response.ok) {
      const detail = data?.detail;

      throw new Error(
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail
                .map((item) => item.msg || JSON.stringify(item))
                .join("; ")
            : fallback
      );
    }

    return data;
  };

  // Send authenticated API requests
  const apiRequest = useCallback(
    async (endpoint, options = {}) => {
      const response = await fetch(`${API_URL}${endpoint}`, {
        ...options,
        headers: {
          Authorization: `Bearer ${token}`,
          ...options.headers,
        },
      });

      return await readResponse(response, "Request failed");
    },
    [token]
  );

  // Load editor dashboard and summary
  const loadDashboard = useCallback(async () => {
    const request = ++dashboardRequest.current;
    const current = () => context.current.token === token && dashboardRequest.current === request;
    setLoading(true);

    try {
      const readInvitations = path => apiRequest(path).then(data => Array.isArray(data) ? data : null).catch(() => null);
      const [manuscriptsData, summaryData, formattingData, initialInvitations, finalInvitations] = await Promise.all([
        apiRequest("/manuscripts/dashboard"),
        apiRequest("/manuscripts/dashboard/summary"),
        apiRequest("/formatting/my"),
        readInvitations('/eic/initial-editing/my'),
        readInvitations('/final-workflow/my'),
      ]);

      if (!Array.isArray(manuscriptsData)) {
        throw new Error("Invalid manuscript data received.");
      }

      if (!Array.isArray(formattingData)) {
        throw new Error("Invalid formatting assignment data received.");
      }

      if (!current()) return false;
      setDashboardOwner(token);
      setManuscripts(manuscriptsData);
      setFormattingAssignments(formattingData);
      setPendingInvitations(pendingEditorInvitations(initialInvitations || [], finalInvitations || []));
      setInvitationWarning(initialInvitations === null || finalInvitations === null);
      setSummary(summaryData);
      setProgressRevision(value => value + 1);
      // Previously fetched review history may be outdated after refresh.
      setReviewHistory({});

      return true;
    } catch (err) {
      if (!current()) return false;
      setDashboardOwner(token);
      setManuscripts([]);
      setFormattingAssignments([]);
      setPendingInvitations([]);
      setInvitationWarning(false);
      setSummary(null);
      setReviewHistory({});
      setError(err.message || "Failed to load dashboard.");
      return false;
    } finally {
      if (current()) setLoading(false);
    }
  }, [apiRequest, token]);

  useEffect(() => {
    loadDashboard();
    return () => { dashboardRequest.current += 1; historyRequest.current += 1; };
  }, [loadDashboard]);

  const safeSummary = dashboardOwner === token ? summary : null;

  // Combine editor manuscripts and formatting assignments.
  // Formatting-only records must never receive general editor permissions.
  const editorManuscriptIds = new Set(
    (dashboardOwner === token ? manuscripts : []).map(item => item.manuscript_id)
  );

  const formattingManuscriptIds = new Set(
    (dashboardOwner === token ? formattingAssignments : []).map(item => item.manuscript_id)
  );

  const accessibleManuscripts = [
    ...(dashboardOwner === token ? manuscripts : []).map(item => ({
      ...item,
      formattingAssigned: formattingManuscriptIds.has(item.manuscript_id),
      formattingOnly: false,
    })),
    ...(dashboardOwner === token ? formattingAssignments : [])
      .filter(item => !editorManuscriptIds.has(item.manuscript_id))
      .map(item => ({
        manuscript_id: item.manuscript_id,
        title: item.title,
        status: item.status,
        formattingAssigned: true,
        formattingOnly: true,
      })),
  ];
  const accessibleIds = new Set(accessibleManuscripts.map(item => item.manuscript_id));
  const pendingByManuscript = new Map((dashboardOwner === token ? pendingInvitations : []).map(item => [item.manuscript_id, item]));
  const allManuscripts = [
    ...accessibleManuscripts.map(item => item.formattingOnly && pendingByManuscript.has(item.manuscript_id)
      ? {...item, invitationKinds: pendingByManuscript.get(item.manuscript_id).invitationKinds}
      : item),
    ...(dashboardOwner === token ? pendingInvitations : []).filter(item => !accessibleIds.has(item.manuscript_id)),
  ].sort((a, b) => a.manuscript_id - b.manuscript_id);

  const stageProjection = useStageProjection(allManuscripts, token, listStatus);

  // Format workflow status
  const formatStatus = (value) =>
    workflowStatusLabel(value);

  // Determine active review round
  const getActiveRound = (manuscript) =>
    manuscript.review_round || (manuscript.status === "revised" ? 2 : 1);

  // Avoid using previous-round counts for revised manuscripts
  const getCurrentRoundProgress = (manuscript) => {
    const activeRound = getActiveRound(manuscript);

    if (activeRound !== manuscript.review_round) {
      return {
        total: 0,
        completed: 0,
        pending: 0,
        reviewStatus: "not_assigned",
      };
    }

    return {
      total: manuscript.total_reviewers ?? 0,
      completed: manuscript.completed_reviews ?? 0,
      pending: manuscript.pending_reviews ?? 0,
      reviewStatus: manuscript.review_status || "not_assigned",
    };
  };

  // Group reviews by round without changing the backend response.
  const groupReviewsByRound = (reviews) => {
    const groups = new Map();
    for (const review of reviews) {
      const value = Number(review.review_round);
      const round = Number.isInteger(value) && value > 0 ? value : null;
      if (!groups.has(round)) groups.set(round, []);
      groups.get(round).push(review);
    }
    return [...groups.entries()].sort(([a], [b]) => a === null ? 1 : b === null ? -1 : a - b);
  };

  // Keep timestamped submissions newest first; preserve input order for unknown dates.
  const orderReviewActivity = (reviews) => [...reviews].sort((a, b) => {
    const time = review => {
      const value = review.submitted_at ? Date.parse(review.submitted_at) : NaN;
      return Number.isFinite(value) ? value : -Infinity;
    };
    const difference = time(b) - time(a);
    return difference || String(a.review_id).localeCompare(String(b.review_id), "en", { numeric: true });
  });

  const getRecommendationSummary = (reviews) => {
    const unique = [...new Set(reviews.map((review) => review.recommendation).filter(Boolean))];
    return {
      conflicting: unique.length > 1,
      unique,
    };
  };

  // Expand or collapse manuscript actions
  const toggleActions = (manuscriptId) => {
    if ((detailDirty || onlineDirty || formattingDirty) && !window.confirm('Leave this manuscript and discard unsaved changes?')) return;
    historyRequest.current += 1; setHistoryLoadingId(null);
    setDetailDirty(false);
    setFormattingDirty(false);
    setOnlineDraftsDirty({});
    setExpandedId((previous) =>
      previous === manuscriptId ? null : manuscriptId
    );

    setError("");
    setMessage("");
  };

  // Manually refresh dashboard
  const handleRefresh = async () => {
    if (actionLock.current || loading) return;

    setError("");
    setMessage("");

    await loadDashboard();
  };
  useReturnRefresh(handleRefresh, detailDirty || onlineDirty || formattingDirty || loading || actionLoadingId !== null);

  // Download manuscript PDF
  const handleDownload = async (manuscriptId) => {
    if (actionLock.current) return;

    const manuscript = manuscripts.find(
      (item) => item.manuscript_id === manuscriptId
    );
    if (!manuscript?.has_pdf) {
      setError("No file is available for this manuscript.");
      return;
    }

    actionLock.current = true;
    setActionLoadingId(manuscriptId);
    setError("");
    setMessage("");

    try {
      const response = await fetch(
        `${API_URL}/manuscripts/${manuscriptId}/download`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (!response.ok) {
        await readResponse(response, "Failed to download manuscript");
        return;
      }

      const blob = await response.blob();

      if (blob.size === 0) {
        throw new Error("Downloaded file is empty.");
      }

      const formats = { "application/pdf": ".pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx", "application/msword": ".doc", "text/plain": ".txt" };
      const extension = formats[(response.headers.get("content-type") || "").split(";")[0].trim().toLowerCase()];
      if (!extension) throw new Error("Unsupported manuscript download format.");
      const url = URL.createObjectURL(blob);

      const link = document.createElement("a");
      link.href = url;
      link.download = `manuscript_${manuscriptId}${extension}`;

      document.body.appendChild(link);
      link.click();
      link.remove();

      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(err.message || "Failed to download manuscript.");
    } finally {
      actionLock.current = false;
      setActionLoadingId(null);
    }
  };

  // Load review history
  const handleViewReviews = async (manuscriptId) => {
    if (historyLoadingId !== null) return;

    const request = ++historyRequest.current;
    const current = () => context.current.token === token && context.current.expandedId === manuscriptId && historyRequest.current === request;
    setHistoryLoadingId(manuscriptId);
    setError("");

    try {
      const data = await apiRequest(
        `/reviews/manuscript/${manuscriptId}`
      );

      if (!Array.isArray(data)) {
        throw new Error("Invalid review history received.");
      }

      if (!current()) return;
      setReviewHistory((previous) => ({
        ...previous,
        [manuscriptId]: data,
      }));
    } catch (err) {
      if (current()) setError(err.message || "Failed to load review history.");
    } finally {
      if (historyRequest.current === request) setHistoryLoadingId(null);
    }
  };

  // Submit editor decision
  const handleDecision = async (manuscript) => {
    if (actionLock.current) return;
    if (manuscript.legacy_editor_decision_allowed !== true) {
      setError(
        "The EIC must make the editorial decision for this manuscript."
      );
      return;
  }
    const manuscriptId = manuscript.manuscript_id;
    const decision = decisions[manuscriptId];
    const progress = getCurrentRoundProgress(manuscript);

    const canDecide =
      ["submitted", "revised"].includes(manuscript.status) &&
      progress.total > 0 &&
      progress.pending === 0 &&
      progress.completed === progress.total;

    if (!canDecide) {
      setError(
        "The current review round must be completed before making a decision."
      );
      return;
    }

    if (
      !["accepted", "rejected", "revision_required"].includes(
        decision
      )
    ) {
      setError("Please select a valid editor decision.");
      return;
    }

    const confirmed = window.confirm(
      `Make decision "${formatStatus(decision)}" for Manuscript #${manuscriptId}?`
    );

    if (!confirmed) return;

    actionLock.current = true;
    setActionLoadingId(manuscriptId);
    setError("");
    setMessage("");

    try {
      await apiRequest(
        `/manuscripts/${manuscriptId}/decision`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ decision }),
        }
      );

      setDecisions((previous) => ({
        ...previous,
        [manuscriptId]: "",
      }));

      const refreshed = await loadDashboard();

      if (refreshed) {
        setMessage(
          `Manuscript #${manuscriptId} updated to "${formatStatus(decision)}".`
        );
      } else {
        setMessage(
          `Decision saved for Manuscript #${manuscriptId}, but the dashboard could not be refreshed.`
        );
      }
    } catch (err) {
      setError(err.message || "Editor decision failed.");
    } finally {
      actionLock.current = false;
      setActionLoadingId(null);
    }
  };
  const returnToManuscripts = () => {
    if ((detailDirty || onlineDirty || formattingDirty) && !window.confirm('Leave this manuscript and discard unsaved changes?')) return false;
    historyRequest.current += 1; setHistoryLoadingId(null);
    setDetailDirty(false); setFormattingDirty(false); setOnlineDraftsDirty({}); setExpandedId(null); setError(""); setMessage("");
    return true;
  };
  useManuscriptReturn(registerManuscriptReturn, returnToManuscripts);
  const handleNotificationNavigate = (notification) => {
    const manuscriptId = notification.manuscript_id;
    if (!allManuscripts.some(item => item.manuscript_id === manuscriptId)) return;
    if (expandedId === manuscriptId) return;
    if (expandedId !== manuscriptId && (detailDirty || onlineDirty || formattingDirty) && !window.confirm('Leave this manuscript and discard unsaved changes?')) return;
    historyRequest.current += 1; setHistoryLoadingId(null);
    setDetailDirty(false); setFormattingDirty(false); setOnlineDraftsDirty({}); setExpandedId(manuscriptId); onSectionChange?.("manuscripts");
  };
  return (
    <div className="editor-page">
      <header className="editor-header">
        <div>
          <h1>{PRODUCT_DISPLAY_NAME} {PRODUCT_SYSTEM_NAME}</h1>
          <p>General / Copy Editor Dashboard · {user.name}</p>
        </div>


        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "12px",
          }}
        >
          <NotificationBell
             token={token}
             onNavigate={handleNotificationNavigate}
             onViewAll={onSectionChange ? () => { if (returnToManuscripts() !== false) onSectionChange("notifications"); } : undefined}
             onAuthorSnapshot={onSectionChange ? receiveNotifications : undefined}
          />
          {accountControl}


        </div>

      </header>

      <main className={`editor-main${section === "dashboard" ? " editor-overview-layout" : ""}${section === "manuscripts" ? " manuscripts-list-layout" : ""}`}>
        {section !== 'notifications' && <aside className={section === 'manuscripts' ? 'manuscripts-list-sidebar' : undefined} aria-label="Manuscript statistics"><EditorAssignmentStatistics token={token} userId={user.user_id} revision={progressRevision} summary={safeSummary} statusItems={accessibleManuscripts} statusLoading={loading || dashboardOwner !== token} statusError={displayError(error)} /></aside>}
        {section === 'dashboard' && <RoleOverview hideStatistics label="Editor" items={allManuscripts} loading={loading} error={displayError(error)} onNavigate={onSectionChange} onOpen={item => handleNotificationNavigate(item)} />}
        {section === 'notifications' && <AuthorNotificationCenter snapshot={notificationSnapshot} token={token} onOpen={handleNotificationNavigate} onBack={() => onSectionChange('dashboard')} />}
        <div className={section === 'manuscripts' ? 'manuscripts-list-content' : undefined} hidden={Boolean(section && section !== 'manuscripts')}>
        <div data-sidebar-target="manuscripts" />

        {error && expandedId === null && (
          <div className="editor-error" role="alert">
            {displayError(error)}
          </div>
        )}

        {message && (
          <div className="editor-success" role="status">
            {message}
          </div>
        )}

        {loading ? (
          <p>Loading dashboard...</p>
        ) : (
          <>
            {/* Manuscript list */}
            <section className={`editor-section${expandedId !== null ? " is-workspace" : ""}`}>
              {expandedId === null && <h2>All Manuscripts</h2>}
              {expandedId === null && invitationWarning && <p role="status">Some editor invitations could not be loaded. Refresh to check them.</p>}

              {section === "manuscripts" && expandedId === null && <StageProjectionNotice projection={stageProjection} />}
              {section === "manuscripts" && expandedId === null && <RoleListControls projection={stageProjection} items={stageProjection.items} search={listSearch} setSearch={setListSearch} status={listStatus} setStatus={setListStatus} sort={listSort} setSort={setListSort} />}
          {section === "manuscripts" && allManuscripts.length > 0 && (listSearch || listStatus) && !stageProjection.loading && !stageProjection.unavailable && selectRoleItems(stageProjection.items, listSearch, listStatus, listSort).length === 0 && <p>No manuscripts match the current filters.</p>}
              {allManuscripts.length === 0 ? (
                <p>No manuscripts found.</p>
              ) : (
                <div className="editor-list">
                  {(expandedId === null && section === "manuscripts" ? selectRoleItems(stageProjection.items, listSearch, listStatus, listSort) : allManuscripts.filter(manuscript => expandedId === null || manuscript.manuscript_id === expandedId)).map((manuscript) => {
                    const manuscriptId = manuscript.manuscript_id;
                    const isExpanded = expandedId === manuscriptId;

                    if (manuscript.invitationOnly) {
                      const refreshAfterInvitation = async () => { if (await loadDashboard()) setExpandedId(null); };
                      return <div id={`manuscript-${manuscriptId}`} className="editor-card" data-workspace={isExpanded ? 'selected' : undefined} key={manuscriptId}>
                        <div className="editor-card-top"><h3>{manuscript.title?.trim() || `Manuscript #${manuscriptId}`}</h3><StatusBadge status={manuscript.status} /></div>
                        {isExpanded ? <>{manuscript.title?.trim() && <p>Manuscript #{manuscriptId}</p>}<p>Pending editor invitation</p></> : <p>Manuscript #{manuscriptId} · Pending editor invitation</p>}
                        <button type="button" className={isExpanded ? 'manuscript-back' : 'editor-manage-button manuscript-open-button'} onClick={() => toggleActions(manuscriptId)}>{isExpanded ? 'Back to manuscripts' : 'Open manuscript'}</button>
                        {isExpanded && <div className="editor-actions">
                          {manuscript.invitationKinds.includes('initial') && <InitialEditingPanel manuscriptId={manuscriptId} role="editor" token={token} onChanged={refreshAfterInvitation} onOnlineDirtyChange={onOnlineDirtyChange} />}
                          {manuscript.invitationKinds.includes('final') && <FinalEditingPanel manuscriptId={manuscriptId} role="editor" token={token} onChanged={refreshAfterInvitation} onOnlineDirtyChange={onOnlineDirtyChange} />}
                        </div>}
                      </div>;
                    }

                    if (manuscript.formattingOnly) {
                      return (
                        <div
                          id={`manuscript-${manuscriptId}`}
                          className="editor-card editor-formatting-card"
                          data-workspace={isExpanded ? "selected" : undefined}
                          key={manuscriptId}
                        >
                          <div className="editor-card-top editor-manuscript-header">
                            <div className="editor-manuscript-title">
                              <h3>{manuscript.title?.trim() || `Manuscript #${manuscriptId}`}</h3>
                              {isExpanded ? <>{manuscript.title?.trim() && <p className="editor-manuscript-meta">Manuscript #{manuscriptId}</p>}<p className="editor-manuscript-meta">Formatting assignment</p></> : <p className="editor-manuscript-meta">{manuscript.title?.trim() && `Manuscript #${manuscriptId} · `}Formatting assignment</p>}
                            </div>
                            <StatusBadge status={manuscript.status} />
                          </div>

                          <button
                            type="button"
                            className={isExpanded ? "manuscript-back" : "editor-manage-button manuscript-open-button"}
                            onClick={() => toggleActions(manuscriptId)}
                          >
                            {isExpanded ? "Back to manuscripts" : "Open manuscript"}
                          </button>

                          {isExpanded && (
                            <div
                              className="editor-actions"
                              onChangeCapture={() => setDetailDirty(true)}
                            >
                              <EditorReceivedDocuments token={token} />
                              <details className="editor-context-panel">
                                <summary>Private Notes</summary>
                                <div className="editor-context-content">
                                  <NotesPanel
                                    manuscriptId={manuscriptId}
                                    token={token}
                                  />
                                </div>
                              </details>

                              <details className="editor-context-panel">
                                <summary>Comments (Staff Shared)</summary>
                                <div className="editor-context-content">
                                  <GeneralCommentsPanel
                                    manuscriptId={manuscriptId}
                                    token={token}
                                  />
                                </div>
                              </details>

                              <h4 className="editor-workflow-heading">Formatting Workflow</h4>

                              {manuscript.invitationKinds?.includes('initial') && <InitialEditingPanel manuscriptId={manuscriptId} role="editor" token={token} onChanged={loadDashboard} onOnlineDirtyChange={onOnlineDirtyChange} />}
                              {manuscript.invitationKinds?.includes('final') && <FinalEditingPanel manuscriptId={manuscriptId} role="editor" token={token} onChanged={loadDashboard} onOnlineDirtyChange={onOnlineDirtyChange} />}

                              <FormattingPanel
                                role="editor"
                                token={token}
                                manuscriptId={manuscriptId}
                                onChanged={loadDashboard}
                                onDirtyChange={setFormattingDirty}
                              />
                            </div>
                          )}
                        </div>
                      );
                    }
                    const isBusy = actionLoadingId !== null;

                    const activeRound = getActiveRound(manuscript);
                    const progress =
                      getCurrentRoundProgress(manuscript);

                    const isFinalized = [
                      "accepted",
                      "rejected",
                    ].includes(manuscript.status);

                    const isOpen = [
                      "submitted",
                      "revised",
                    ].includes(manuscript.status);

                    const legacyDecisionAllowed =
                      manuscript.legacy_editor_decision_allowed === true;

                    const canDecide =
                      legacyDecisionAllowed &&
                      isOpen &&
                      manuscript.decision_progress?.can_decide &&
                      progress.total > 0 &&
                      progress.pending === 0 &&
                      progress.completed === progress.total;

                    return (
                      <div
                        id={`manuscript-${manuscriptId}`}
                        className="editor-card"
                        data-workspace={isExpanded ? "selected" : undefined}
                        key={manuscriptId}
                      >
                        <div className="editor-card-top editor-manuscript-header">
                          <div className="editor-manuscript-title">
                            <h3>{manuscript.title?.trim() || `Manuscript #${manuscriptId}`}</h3>
                            {isExpanded ? <>{manuscript.title?.trim() && <p className="editor-manuscript-meta">Manuscript #{manuscriptId}</p>}{Number.isInteger(manuscript.review_round) && manuscript.review_round > 0 && <p className="editor-manuscript-meta">Review round {manuscript.review_round}</p>}</> : (manuscript.title?.trim() || (Number.isInteger(manuscript.review_round) && manuscript.review_round > 0)) && <p className="editor-manuscript-meta">
                              {manuscript.title?.trim() && `Manuscript #${manuscriptId}`}
                              {Number.isInteger(manuscript.review_round) && manuscript.review_round > 0 && <>{manuscript.title?.trim() && ' · '}Review round {manuscript.review_round}</>}
                            </p>}
                          </div>

                          <StatusBadge status={manuscript.status} />
                        </div>

                        {isExpanded && (
                          <div onChangeCapture={() => setDetailDirty(true)}>
                            <details className="editor-context-panel">
                              <summary>Private Notes</summary>
                              <div className="editor-context-content">
                                <NotesPanel manuscriptId={manuscriptId} token={token} />
                              </div>
                            </details>
                            <details className="editor-context-panel">
                              <summary>Comments (Staff Shared)</summary>
                              <div className="editor-context-content">
                                <GeneralCommentsPanel manuscriptId={manuscriptId} token={token} />
                              </div>
                            </details>
                          </div>
                        )}
                        {isExpanded && (
                          <section className="editor-overview">
                            <div className="editor-overview-heading">
                              <div>
                                <h4>Manuscript Overview</h4>
                                <p>Current review progress and workflow status</p>
                              </div>
                            </div>

                            <div className="editor-overview-progress">
                              <ManuscriptProgress showTitle={false} showRound={!(Number.isInteger(manuscript.review_round) && manuscript.review_round > 0)}
                                key={manuscriptId}
                                manuscriptId={manuscriptId}
                                token={token}
                                revision={progressRevision}
                              />
                            </div>
                            <ManuscriptTimeline manuscriptId={manuscriptId} token={token} revision={progressRevision} />

                            <div className="editor-overview-stats">
                              <div className="editor-overview-stat">
                                <span>Completed reviews</span>
                                <strong>{progress.completed}/{progress.total}</strong>
                                <small>Reviews submitted</small>
                              </div>

                              <div className="editor-overview-stat">
                                <span>Pending reviews</span>
                                <strong>{progress.pending}</strong>
                                <small>Awaiting completion</small>
                              </div>

                              {manuscript.decision_progress && (
                                <div className="editor-overview-stat">
                                  <span>Decision progress</span>
                                  <strong>
                                    {Math.min(
                                      manuscript.decision_progress.completed_distinct,
                                      manuscript.decision_progress.required
                                    )}/{manuscript.decision_progress.required}
                                  </strong>
                                  <small>
                                    {manuscript.decision_progress.policy === "legacy"
                                      ? "Historical review requirement"
                                      : "Required completed reviews"}
                                  </small>
                                </div>
                              )}
                            </div>

                            <div className="editor-overview-status">
                              <div>
                                <span>Review status</span>
                                <strong className={`editor-review-badge ${progress.reviewStatus}`}>
                                  {formatStatus(progress.reviewStatus)}
                                </strong>
                              </div>

                              {manuscript.author_agreement_status && (
                                <div>
                                  <span>Author Agreement</span>
                                  <strong className={`editor-review-badge ${manuscript.author_agreement_status}`}>
                                    {formatStatus(manuscript.author_agreement_status)}
                                  </strong>
                                </div>
                              )}
                            </div>

                            {manuscript.author_agreement_status &&
                              manuscript.author_agreement_status !== "accepted" && (
                                <p className="editor-overview-warning">
                                  Final editing is currently on hold until the author agreement is accepted.
                                </p>
                              )}

                            {["ready_for_peer_review", "revised"].includes(manuscript.status) &&
                              manuscript.decision_progress?.blocked_reason && (
                                <p className="editor-overview-warning">
                                  Decision blocked: {manuscript.decision_progress.blocked_reason}
                                </p>
                              )}
                          </section>
                        )}

                        <button
                          type="button"
                          className={isExpanded ? "manuscript-back" : "editor-manage-button manuscript-open-button"}
                          onClick={() => toggleActions(manuscriptId)}
                        >
                          {isExpanded
                            ? "Back to manuscripts"
                            : "Open manuscript"}
                        </button>

                        {isExpanded && (
                          <div className="editor-actions" onChangeCapture={() => setDetailDirty(true)}>
                            <EditorReceivedDocuments token={token} />
                            <h4 className="editor-workflow-heading">Manuscript Workflow</h4>
                            <div id={`final-editing-action-${manuscriptId}`}><FinalEditingPanel key={`final-${manuscriptId}`} manuscriptId={manuscriptId} role="editor" token={token} onChanged={loadDashboard} onOnlineDirtyChange={onOnlineDirtyChange} /></div>
                            <div id={`initial-editing-action-${manuscriptId}`}><InitialEditingPanel key={`initial-${manuscriptId}`} manuscriptId={manuscriptId} role="editor" token={token} onChanged={loadDashboard} onOnlineDirtyChange={onOnlineDirtyChange} /></div>
                            {manuscript.formattingAssigned && (
                              <FormattingPanel
                                key={`formatting-${manuscriptId}`}
                                manuscriptId={manuscriptId}
                                role="editor"
                                showProgress={false}
                                token={token}
                                onChanged={loadDashboard}
                                onDirtyChange={setFormattingDirty}
                              />
                            )}
                            {error && (
                              <div className="editor-error" role="alert">
                                {displayError(error)}
                              </div>
                            )}
                            {/* PDF Download */}
                            <div className="editor-action-block">
                              <h4>Manuscript PDF</h4>

                              {manuscript.has_pdf ? (
                                <button
                                  type="button"
                                  className="editor-secondary-button"
                                  disabled={isBusy}
                                  onClick={() =>
                                    handleDownload(manuscriptId)
                                  }
                                >
                                  {actionLoadingId === manuscriptId
                                    ? "Processing..."
                                    : "Download file"}
                                </button>
                              ) : (
                                <p>No PDF uploaded</p>
                              )}
                            </div>

                            <ReviewerInvitationPanel manuscriptId={manuscriptId} round={activeRound} status={manuscript.status} token={token} />
<EmailDemoPanel />

                            {/* Review History */}
                            <div className="editor-action-block">
                              <h4>Reviewer Comments</h4>

                              <button
                                type="button"
                                className="editor-secondary-button"
                                disabled={
                                  historyLoadingId !== null
                                }
                                onClick={() =>
                                  handleViewReviews(manuscriptId)
                                }
                              >
                                {historyLoadingId === manuscriptId
                                  ? "Loading..."
                                  : "View Reviews"}
                              </button>

                              {reviewHistory[manuscriptId] && (
                                <div className="editor-review-list">
                                  {reviewHistory[manuscriptId].length === 0 ? (
                                    <p className="editor-review-empty">
                                      No reviews submitted yet.
                                    </p>
                                  ) : (
                                    groupReviewsByRound(reviewHistory[manuscriptId]).map(
                                      ([round, reviews]) => {
                                        const summary = getRecommendationSummary(reviews);

                                        return (
                                          <section
                                            className="editor-review-round"
                                            key={round}
                                          >
                                            <div className="editor-review-round-header">
                                              <div>
                                                <span className="editor-review-eyebrow">
                                                  PEER REVIEW
                                                </span>
                                                <h4>{round === null ? 'Review round unavailable' : `Review round ${round}`}</h4>
                                              </div>

                                              <span className="editor-review-count">
                                                {reviews.length} submitted
                                              </span>
                                            </div>

                                            <div className="editor-review-summary">
                                              {reviews.map(review => (
                                                <div
                                                  className="editor-review-summary-item"
                                                  key={review.review_id}
                                                >
                                                  <span>
                                                    Reviewer #{review.reviewer_id}
                                                  </span>
                                                  <strong className={`editor-recommendation ${review.recommendation}`}>
                                                    {formatStatus(review.recommendation)}
                                                  </strong>
                                                </div>
                                              ))}
                                            </div>

                                            {summary.conflicting && (
                                              <div
                                                className="editor-review-conflict"
                                                role="status"
                                              >
                                                <strong>Conflicting recommendations</strong>
                                                <p>
                                                  Reviewers disagree in Round {round}.
                                                  The editor must evaluate their comments
                                                  before making the final decision.
                                                </p>
                                              </div>
                                            )}

                                            <div className="editor-review-comments">
                                              <h5>Reviewer Comments</h5>

                                              {reviews.map(review => (
                                                <article
                                                  className="editor-review-item"
                                                  key={review.review_id}
                                                >
                                                  <div className="editor-review-item-header">
                                                    <strong>
                                                      Reviewer #{review.reviewer_id}
                                                    </strong>
                                                    <span className={`editor-recommendation ${review.recommendation}`}>
                                                      {formatStatus(review.recommendation)}
                                                    </span>
                                                  </div>

                                                  <p>
                                                    {review.comments || "No comments provided."}
                                                  </p>
                                                </article>
                                              ))}
                                            </div>
                                          </section>
                                        );
                                      }
                                    )
                                  )}
                                </div>
                              )}
                            </div>

                            {reviewHistory[manuscriptId] && (
                              <details className="editor-action-block">
                                <summary>Activity History</summary>
                                <p>Recorded review submissions</p>
                                {reviewHistory[manuscriptId].length === 0 ? (
                                  <p>No review submissions recorded.</p>
                                ) : (
                                  <ul>
                                    {orderReviewActivity(reviewHistory[manuscriptId]).map(review => {
                                      const submitted = new Date(review.submitted_at);
                                      const validDate = review.submitted_at && !Number.isNaN(submitted.getTime());
                                      return <li key={review.review_id}>
                                        Review submitted · Round {review.review_round}
                                        {validDate ? <> · <time dateTime={review.submitted_at}>{submitted.toLocaleString()}</time></> : <> · Date unavailable</>}
                                      </li>;
                                    })}
                                  </ul>
                                )}
                              </details>
                            )}

                            {/* Editor Decision */}
                            {!isFinalized && (
                              <section className="editor-decision-card">
                                <div className="editor-decision-header">
                                  <div>
                                    <span className="editor-decision-eyebrow">
                                      EDITORIAL WORKFLOW
                                    </span>
                                    <h4>Editor Decision</h4>
                                    <p>Review the completed evaluations and select an editorial decision.</p>
                                  </div>
                                  <span className="editor-decision-status">
                                    {legacyDecisionAllowed
                                      ? canDecide ? "Ready for decision" : "Awaiting Reviews"
                                      : "EIC Decision"}
                                  </span>
                                </div>

                                {!legacyDecisionAllowed ? (
                                  <div className="editor-decision-notice">
                                    <strong>Editorial decision required by EIC</strong>
                                    <p>
                                      The EIC makes the editorial decision for this manuscript.
                                    </p>
                                  </div>
                                ) : canDecide ? (
                                  <div className="editor-decision-content">
                                    <div className="editor-decision-ready">
                                      <span className="editor-decision-check">✓</span>
                                      <div>
                                        <strong>All reviews completed</strong>
                                        <p>
                                          All assigned reviewers have submitted their reviews.
                                        </p>
                                      </div>
                                    </div>

                                    {reviewHistory[manuscriptId] &&
                                      getRecommendationSummary(
                                        reviewHistory[manuscriptId].filter(
                                          review => Number(review.review_round) === activeRound
                                        )
                                      ).conflicting && (
                                        <div className="editor-decision-conflict" role="status">
                                          <strong>Reviewer recommendations conflict</strong>
                                          <p>
                                            Current-round reviewers disagree. Please evaluate
                                            their comments carefully before submitting a decision.
                                          </p>
                                        </div>
                                      )}

                                    <div className="editor-decision-form">
                                      <label htmlFor={`decision-${manuscriptId}`}>
                                        Final editorial decision
                                      </label>

                                      <select
                                        id={`decision-${manuscriptId}`}
                                        className="editor-decision-select"
                                        value={decisions[manuscriptId] || ""}
                                        disabled={isBusy}
                                        onChange={event =>
                                          setDecisions(previous => ({
                                            ...previous,
                                            [manuscriptId]: event.target.value,
                                          }))
                                        }
                                      >
                                        <option value="">Select a decision</option>
                                        <option value="accepted">Accept</option>
                                        <option value="rejected">Reject</option>
                                        <option value="revision_required">Request revision</option>
                                      </select>

                                      <button
                                        type="button"
                                        className="editor-primary-button editor-decision-submit"
                                        disabled={
                                          isBusy ||
                                          !decisions[manuscriptId]
                                        }
                                        onClick={() => handleDecision(manuscript)}
                                      >
                                        {actionLoadingId === manuscriptId
                                          ? "Processing..."
                                          : "Submit Decision"}
                                      </button>
                                    </div>
                                  </div>
                                ) : (
                                  <div className="editor-decision-waiting">
                                    <span className="editor-decision-waiting-icon">◷</span>
                                    <div>
                                      <strong>Review round in progress</strong>
                                      <p>
                                        A decision is unavailable until the current review round is complete.
                                      </p>
                                    </div>
                                  </div>
                                )}
                              </section>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          </>
        )}
        </div>
      </main>
    </div>
  );
}

export default EditorDashboard;
