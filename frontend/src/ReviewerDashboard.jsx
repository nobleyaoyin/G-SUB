import {displayError} from './displayError';
import './ManuscriptsListLayout.css';
import {workflowStatusLabel} from './workflowStatus';
import useStageProjection, {StageProjectionNotice} from './useStageProjection';
import CollapsibleStatistics from './CollapsibleStatistics';
import ReviewerManuscriptCard from './ReviewerManuscriptCard';
import RoleListControls, { selectRoleItems } from "./RoleListControls";
import RoleOverview from "./RoleOverview";
import AuthorNotificationCenter from "./AuthorNotificationCenter";
import ManuscriptTimeline from "./ManuscriptTimeline";
import { ReviewerDocumentUpload, ReviewerDocumentHistory } from "./DocumentDistribution";
import useManuscriptReturn from "./useManuscriptReturn";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import "./ReviewerDashboard.css";
import NotificationBell from "./NotificationBell";
import ReviewerProfilePanel from "./ReviewerProfilePanel";
import useReturnRefresh from "./useReturnRefresh";
import ManuscriptProgress from "./ManuscriptProgress";
import { PRODUCT_DISPLAY_NAME, PRODUCT_SYSTEM_NAME } from "./branding";

import { API_URL } from "./api";

function ReviewerWorkspace({ user, token, accountControl, onProfileDirtyChange, registerManuscriptReturn, section, onSectionChange }) {
  const [listSearch, setListSearch] = useState("");
  const [listStatus, setListStatus] = useState("");
  const [listSort, setListSort] = useState("recent");
  const [notificationSnapshot, setNotificationSnapshot] = useState(null);
  const receiveNotifications = useCallback(snapshot => setNotificationSnapshot(snapshot), []);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileDirty, setProfileDirty] = useState(false);
  const profileDirtyChanged = useCallback(value => { setProfileDirty(value); onProfileDirtyChange?.(value); }, [onProfileDirtyChange]);
  const [assignments, setAssignments] = useState([]);
  const assignmentRequest = useRef(0);
  const activeToken = useRef(token);
  activeToken.current = token;
  const [selectedId, setSelectedId] = useState(null);
  const activeSelection = useRef(selectedId);
  activeSelection.current = selectedId;
  const downloadGeneration = useRef(0);
  const downloadRequests = useRef(new Map());
  const workspaceMounted = useRef(false);
  useLayoutEffect(() => {
    workspaceMounted.current = true;
    return () => { workspaceMounted.current = false; downloadGeneration.current += 1; downloadRequests.current.clear(); };
  }, []);
  const selectionVersion = useRef(0);
  useEffect(() => { selectionVersion.current += 1; }, [selectedId]);
  const [reviews, setReviews] = useState({});
  const [details, setDetails] = useState({});
  const [progressRevision, setProgressRevision] = useState(0);
  const [documentRevision, setDocumentRevision] = useState(0);
  const [taskResult, setTaskResult] = useState(null);
  const [ownReview, setOwnReview] = useState(null);

  useEffect(() => {
    const assignment = assignments.find(item => item.assignment_id === selectedId);
    setOwnReview(null);
    if (!assignment || assignment.status !== 'completed' || !Number.isSafeInteger(assignment.manuscript_id) || !Number.isSafeInteger(assignment.review_round)) return undefined;
    const controller = new AbortController();
    const context = { token, assignmentId: selectedId, manuscriptId: assignment.manuscript_id, round: assignment.review_round };
    setOwnReview({ ...context, loading: true });
    fetch(`${API_URL}/reviews/my/manuscripts/${context.manuscriptId}/rounds/${context.round}/assignments/${context.assignmentId}`, {
      headers: { Authorization: `Bearer ${token}` }, signal: controller.signal, cache: 'no-store',
    }).then(async response => {
      if (!response.ok) throw new Error('Review unavailable');
      const data = await response.json();
      if (data.assignment_id !== context.assignmentId || data.manuscript_id !== context.manuscriptId || data.review_round !== context.round ||
          typeof data.comments !== 'string' || typeof data.recommendation !== 'string' || typeof data.submitted_at !== 'string') throw new Error('Invalid review');
      if (!controller.signal.aborted) setOwnReview({ ...context, data });
    }).catch(() => { if (!controller.signal.aborted) setOwnReview({ ...context, error: true }); });
    return () => controller.abort();
  }, [assignments, selectedId, token, progressRevision]);

  useEffect(() => {
    if (selectedId == null) return undefined;
    const controller = new AbortController();
    const context = { token, id: selectedId, revision: progressRevision };
    setTaskResult(null);
    async function loadTask() {
      try {
        const response = await fetch(`${API_URL}/assignments/${selectedId}/task`, {
          headers: { Authorization: `Bearer ${token}` }, signal: controller.signal, cache: 'no-store',
        });
        if (!response.ok) throw new Error('Task unavailable');
        const data = await response.json();
        if (!['pending','declined','waiting','stale','unavailable','no_action','action_required'].includes(data?.task_state) ||
            data.relevant_stage !== 'Peer Review' || typeof data.task_message !== 'string' || !data.task_message.trim()) throw new Error('Invalid task');
        if (!controller.signal.aborted) setTaskResult({ ...context, task: data });
      } catch {
        if (!controller.signal.aborted) setTaskResult({ ...context, task: { task_state:'unavailable', task_message:'Assignment task information is unavailable.' } });
      }
    }
    loadTask();
    return () => controller.abort();
  }, [selectedId, token, progressRevision]);

  const [loading, setLoading] = useState(true);
  const [submittingId, setSubmittingId] = useState(null);
  const [downloadingIds, setDownloadingIds] = useState(() => new Set());

  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  // Prevent repeated clicks before React updates the UI
  const submittingRef = useRef(false);

  // Handle API responses
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

  // Load assignments for the current reviewer
  const loadAssignments = useCallback(async (stillCurrent = () => true) => {
    if (activeToken.current !== token || !stillCurrent()) return false;
    const request = ++assignmentRequest.current;
    setLoading(true);
    setAssignments(previous => previous.map(item => ({ ...item, review_file_available: false, review_file_status: 'unavailable' })));

    try {
      const response = await fetch(
        `${API_URL}/assignments/my`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      const contentType =
        response.headers.get("content-type") || "";

      const data = contentType.includes("application/json")
        ? await response.json()
        : null;

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : "Failed to load assignments"
        );
      }

      if (!Array.isArray(data)) {
        throw new Error("Invalid assignment data received.");
      }

      if (request !== assignmentRequest.current || !stillCurrent()) return false;
      setAssignments(data);
      setProgressRevision(value => value + 1);
      setError("");
      return true;
    } catch (err) {
      if (request !== assignmentRequest.current || !stillCurrent()) return false;
      setError(err.message || "Failed to load assignments.");
      return false;
    } finally {
      if (request === assignmentRequest.current) setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadAssignments();
    return () => { assignmentRequest.current += 1; };
  }, [loadAssignments]);

  // Manually refresh assignments
  const handleRefresh = async () => {
    setError("");
    setMessage("");
    await loadAssignments();
  };
  useReturnRefresh(handleRefresh, Boolean(reviews[selectedId]?.comments || reviews[selectedId]?.recommendation) || loading || submittingId !== null || downloadingIds.size > 0);

  const openDetails = async assignment => {
    const version = selectionVersion.current;
    setError("");
    try {
      const response = await fetch(`${API_URL}/manuscripts/${assignment.manuscript_id}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      const data = await readResponse(response, "Manuscript details unavailable.");
      if (version !== selectionVersion.current || activeSelection.current !== assignment.assignment_id) return;
      if (data?.manuscript_id !== assignment.manuscript_id) throw new Error("Invalid manuscript details.");
      setDetails(previous => ({ ...previous, [assignment.assignment_id]: data }));
    } catch (e) { if (version === selectionVersion.current && activeSelection.current === assignment.assignment_id) setError(e.message || "Manuscript details unavailable."); }
  };

  const respondInvitation = async (assignmentId, decision) => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setSubmittingId(assignmentId); setError(""); setMessage("");
    try {
      const response = await fetch(`${API_URL}/assignments/${assignmentId}/invitation-response`, {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ decision }),
      });
      await readResponse(response, "Invitation response failed");
      await loadAssignments();
      setMessage(`Invitation ${decision === "accept" ? "accepted" : "declined"}.`);
    } catch (err) { setError(err.message || "Invitation response failed."); }
    finally { submittingRef.current = false; setSubmittingId(null); }
  };

  // Update review form values
  const handleReviewChange = (assignmentId, field, value) => {
    setReviews((previous) => ({
      ...previous,
      [assignmentId]: {
        ...previous[assignmentId],
        [field]: value,
      },
    }));
  };

  // Submit a review
  const handleSubmitReview = async (assignmentId) => {
    if (submittingRef.current) return;

    const review = reviews[assignmentId] || {};

    if (!review.comments?.trim() || !review.recommendation) {
      setError("Please enter comments and select a recommendation.");
      return;
    }

    if (
      !["accept", "revision", "reject"].includes(
        review.recommendation
      )
    ) {
      setError("Please select a valid recommendation.");
      return;
    }

    const version = selectionVersion.current;
    const isCurrent = () => workspaceMounted.current && activeToken.current === token && activeSelection.current === assignmentId && selectionVersion.current === version;
    submittingRef.current = true;
    setSubmittingId(assignmentId);

    setError("");
    setMessage("");

    try {
      const response = await fetch(`${API_URL}/reviews/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          assignment_id: assignmentId,
          comments: review.comments.trim(),
          recommendation: review.recommendation,
        }),
      });

      await readResponse(response, "Review submission failed");
      if (!isCurrent()) return;

      // Clear the submitted review form
      setReviews((previous) => {
        const updated = { ...previous };
        delete updated[assignmentId];
        return updated;
      });

      // Reload assignments to show the completed status
      const refreshed = await loadAssignments(isCurrent);
      if (!isCurrent()) return;

      if (refreshed) {
        setMessage(
          `Review submitted successfully for Assignment #${assignmentId}.`
        );
      } else {
        setMessage(
          `Review submitted for Assignment #${assignmentId}, but the assignment list could not be refreshed.`
        );
      }
    } catch (err) {
      if (isCurrent()) setError(err.message || "Review submission failed.");
    } finally {
      submittingRef.current = false;
      setSubmittingId(null);
    }
  };

  // Download the file bound to this assignment.
  const handleDownload = async (assignmentId, available) => {
    const version = selectionVersion.current;
    if (downloadRequests.current.has(assignmentId)) return;

    if (!available) {
      setError("The review file is unavailable. Contact the editorial team.");
      return;
    }

    const request = { generation: ++downloadGeneration.current };
    downloadRequests.current.set(assignmentId, request);
    const isCurrent = () => workspaceMounted.current && downloadRequests.current.get(assignmentId) === request && activeToken.current === token && activeSelection.current === assignmentId && version === selectionVersion.current;
    setDownloadingIds(previous => new Set(previous).add(assignmentId));
    setError("");
    setMessage("");

    try {
      const response = await fetch(
        `${API_URL}/assignments/${assignmentId}/download`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (!response.ok) {
        await readResponse(response, "Review file download failed");
        return;
      }

      const blob = await response.blob();
      if (!isCurrent()) return;

      if (blob.size === 0) {
        throw new Error("Downloaded review file is empty.");
      }

      const formats = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/msword": ".doc",
        "text/plain": ".txt",
      };
      const extension = formats[(response.headers.get("content-type") || "").split(";")[0].trim().toLowerCase()];
      if (!extension) throw new Error("Unsupported review file format.");
      const disposition = response.headers.get("content-disposition") || "";
      const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
      const plain = disposition.match(/filename="([^"]+)"|filename=([^;]+)/i);
      let filename = "";
      try {
        filename = encoded ? decodeURIComponent(encoded[1]) : (plain?.[1] || plain?.[2] || "").trim();
      } catch {
        filename = "";
      }
      filename = filename.split(/[\\/]/).pop();
      if (!filename || !filename.toLowerCase().endsWith(extension) || [...filename].some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)) {
        filename = `review_assignment_${assignmentId}${extension}`;
      }
      const urlApi = URL;
      const create = urlApi.createObjectURL;
      const revoke = urlApi.revokeObjectURL;
      if (typeof create !== 'function' || typeof revoke !== 'function') throw new Error('Review file download is unavailable.');
      let link;
      let attempted = false;
      let url;
      const cleanupUrl = () => {
        if (attempted) return;
        attempted = true;
        try { revoke.call(urlApi, url); } catch { /* Cleanup was attempted. */ }
      };
      url = create.call(urlApi, blob);
      try {
        link = document.createElement("a");
        link.href = url;
        link.download = filename;
        if (isCurrent()) {
          document.body.appendChild(link);
          link.click();
        }
      } finally {
        try { link?.remove(); }
        finally {
          try { setTimeout(cleanupUrl, 1000); }
          catch { cleanupUrl(); }
        }
      }
    } catch (err) {
      const failure = err.message || "Review file download failed.";
      if (isCurrent()) {
        await loadAssignments(isCurrent);
        if (isCurrent()) setError(failure);
      }
    } finally {
      if (downloadRequests.current.get(assignmentId) === request) {
        downloadRequests.current.delete(assignmentId);
        if (workspaceMounted.current) setDownloadingIds(previous => {
          const next = new Set(previous); next.delete(assignmentId); return next;
        });
      }
    }
  };

  // Dashboard statistics
  const completedCount = assignments.filter(
    (assignment) => assignment.status === "completed"
  ).length;

  const pendingCount = assignments.filter(
    (assignment) => assignment.status === "assigned" && assignment.invitation_status !== "declined"
  ).length;

  const discardReview = id => {
    if (id === null) return;
    setReviews(previous => { const next = { ...previous }; delete next[id]; return next; });
  };
  const returnToManuscripts = () => {
    const review = reviews[selectedId] || {};
    if (profileDirty && !window.confirm("Discard unsaved profile changes?")) return false;
    if ((review.comments || review.recommendation) && !window.confirm('Leave this review and discard unsaved changes?')) return false;
    discardReview(selectedId);
    setSelectedId(null);
    if (profileDirty) profileDirtyChanged(false);
    setProfileOpen(false);
    return true;
  };
  useManuscriptReturn(registerManuscriptReturn, returnToManuscripts);

  const handleNotificationNavigate = (notification) => {
    const manuscriptId = notification.manuscript_id;
    const target = assignments.filter(item => item.manuscript_id === manuscriptId)
      .sort((a, b) => b.review_round - a.review_round)[0];
    if (!target) return;
    if (profileDirty && !window.confirm("Discard unsaved profile changes?")) return;
    const current = reviews[selectedId] || {};
    if (selectedId !== null && selectedId !== target.assignment_id && (current.comments || current.recommendation) && !window.confirm('Leave this review and discard unsaved changes?')) return;
    if (selectedId !== target.assignment_id) discardReview(selectedId);
    if (profileDirty) profileDirtyChanged(false); setProfileOpen(false);
    setSelectedId(target.assignment_id); onSectionChange?.("manuscripts");
  };

  const stageProjection = useStageProjection(assignments, token, listStatus, true);

  return (
    <div className="reviewer-page">
      <header className="reviewer-header">
        <div>
          <h1>{PRODUCT_DISPLAY_NAME} {PRODUCT_SYSTEM_NAME}</h1>
          <p>Reviewer Dashboard · {user.name}</p>
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

      <main className={`reviewer-main${section === 'dashboard' || section === 'manuscripts' ? ' reviewer-main-list-layout' : ''}`}>
        {section === 'dashboard' && <RoleOverview label="Reviewer" items={assignments} loading={loading} error={displayError(error)} onNavigate={onSectionChange} onOpen={item => handleNotificationNavigate(item)} />}
        {section === 'notifications' && <AuthorNotificationCenter snapshot={notificationSnapshot} token={token} onOpen={handleNotificationNavigate} onBack={() => onSectionChange('dashboard')} />}
        <div className={section === 'manuscripts' ? 'manuscripts-list-layout reviewer-list-layout' : undefined} hidden={Boolean(section && section !== 'manuscripts')}>
        <aside className={section === 'manuscripts' ? 'manuscripts-list-sidebar author-statistics-sidebar' : undefined} aria-label="Manuscript statistics">
        <CollapsibleStatistics className={section === 'manuscripts' && selectedId === null ? 'dashboard-collapsible' : 'reviewer-collapsible reviewer-stats-collapsible'}>
          {error ? <p>Statistics are unavailable.</p> : loading ? <p role="status">Loading statistics…</p> : <div className={section === 'manuscripts' && selectedId === null ? 'stats-grid' : 'reviewer-stats'}>
          <div className={section === 'manuscripts' && selectedId === null ? 'stat-card' : 'reviewer-stat-card'}>
            <span>Total assignments</span>
            <strong>{assignments.length}</strong>
          </div>

          <div className={section === 'manuscripts' && selectedId === null ? 'stat-card' : 'reviewer-stat-card'}>
            <span>Completed</span>
            <strong>{completedCount}</strong>
          </div>

          <div className={section === 'manuscripts' && selectedId === null ? 'stat-card' : 'reviewer-stat-card'}>
            <span>Pending</span>
            <strong>{pendingCount}</strong>
          </div>
          </div>}
        </CollapsibleStatistics>
        </aside>
        <div className={section === 'manuscripts' ? 'manuscripts-list-content' : undefined}>
        <h2>Welcome, {user.name}!</h2>

        <p className="reviewer-description">
          Review assigned manuscripts and submit your recommendations.
        </p>

        <div hidden={selectedId !== null}><button type="button" className="download-button reviewer-profile-button" aria-expanded={profileOpen} aria-controls="reviewer-profile-section" onClick={() => {
          if (profileOpen && profileDirty && !window.confirm("Discard unsaved profile changes?")) return;
          if (profileOpen) profileDirtyChanged(false);
          setProfileOpen(value => !value);
        }}>My professional profile</button>
        <div id="reviewer-profile-section">{profileOpen && <ReviewerProfilePanel token={token} onDirtyChange={profileDirtyChanged} />}</div></div>



        {error && (
          <div className="reviewer-error" role="alert">
            {displayError(error)}
          </div>
        )}

        {message && (
          <div className="reviewer-success" role="status">
            {message}
          </div>
        )}

        <section className={`reviewer-section${selectedId !== null ? " is-workspace" : ""}`} data-sidebar-target="manuscripts">
          <div className="reviewer-section-header">
            {selectedId === null && <h2>My Review Assignments</h2>}

          </div>

          {section === "manuscripts" && selectedId === null && <StageProjectionNotice projection={stageProjection} />}
          {section === "manuscripts" && selectedId === null && <RoleListControls projection={stageProjection} items={stageProjection.items} search={listSearch} setSearch={setListSearch} status={listStatus} setStatus={setListStatus} sort={listSort} setSort={setListSort} />}
          {section === "manuscripts" && assignments.length > 0 && (listSearch || listStatus) && !stageProjection.loading && !stageProjection.unavailable && selectRoleItems(stageProjection.items, listSearch, listStatus, listSort).length === 0 && <p>No manuscripts match the current filters.</p>}
          {loading ? (
            <p>Loading assignments...</p>
          ) : assignments.length === 0 ? (
            <p>No review assignments found.</p>
          ) : (
            <div className="reviewer-list">
              {(selectedId === null && section === "manuscripts" ? selectRoleItems(stageProjection.items, listSearch, listStatus, listSort) : assignments.filter(assignment => selectedId === null || assignment.assignment_id === selectedId)).map((assignment) => {
                const assignmentId = assignment.assignment_id;
                const review = reviews[assignmentId] || {};

                const isCompleted =
                  assignment.status === "completed";

                const taskIsStale = taskResult?.token === token && taskResult?.id === assignmentId && taskResult?.revision === progressRevision && taskResult?.task?.task_state === 'stale';
                const isAssigned =
                  !taskIsStale && assignment.status === "assigned" && ["accepted", "legacy"].includes(assignment.invitation_status);

                const invitationPending = !taskIsStale && assignment.invitation_status === "pending";
                const invitationDeclined = assignment.invitation_status === "declined";

                if (selectedId === null) return <ReviewerManuscriptCard key={assignmentId} assignment={assignment} onOpen={() => setSelectedId(assignmentId)} />;

                const isSubmitting =
                  submittingId === assignmentId;


                return (
                  <div
                    id={`assignment-${assignmentId}`}
                    data-manuscript-id={assignment.manuscript_id}
                    data-review-round={assignment.review_round}
                    data-workspace="selected"
                    className="reviewer-card"
                    key={assignmentId}
                  >

                    <button type="button" className="manuscript-back" onClick={() => { if ((review.comments || review.recommendation) && !window.confirm('Leave this review and discard unsaved changes?')) return; discardReview(assignmentId); setSelectedId(null); }}>Back to manuscripts</button>

                    <div className="reviewer-card-top">
                      <h3>
                        {assignment.manuscript_title?.trim() ||
                          `Manuscript #${assignment.manuscript_id}`}
                      </h3>

                      <span
                        className={`reviewer-status ${assignment.status}`}
                      >
                        {workflowStatusLabel(assignment.status)}
                      </span>
                    </div>

                    {assignment.manuscript_title?.trim() && <p className="reviewer-meta">Manuscript #{assignment.manuscript_id}</p>}

                    {['accepted', 'legacy'].includes(assignment.invitation_status) && ['assigned', 'completed'].includes(assignment.status)
                      ? <ManuscriptProgress showTitle={false} showNextAction={false} showRound={!(Number.isInteger(assignment.review_round) && assignment.review_round > 0)} key={`${assignment.manuscript_id}-${progressRevision}`} manuscriptId={assignment.manuscript_id} token={token} />
                      : <p>Progress is available after the invitation is accepted.</p>}
                    {['accepted', 'legacy'].includes(assignment.invitation_status) && ['assigned', 'completed'].includes(assignment.status) && <ManuscriptTimeline manuscriptId={assignment.manuscript_id} token={token} revision={progressRevision} />}
                    <p className="reviewer-meta"><strong>Next action:</strong> {taskResult?.token === token && taskResult?.id === assignmentId && taskResult?.revision === progressRevision && !error ? <>{taskResult.task.task_message} ({workflowStatusLabel(taskResult.task.task_state)}){isAssigned && taskResult.task.task_state === 'action_required' && taskResult.task.action_label === 'View review form' && taskResult.task.permitted_action_target === `#review-action-${assignmentId}` && <> <a href={taskResult.task.permitted_action_target}>{taskResult.task.action_label}</a></>}</> : 'Assignment task information is unavailable or loading.'}</p>
                    <h4>Manuscript Information</h4>

                    {assignment.manuscript_status && <p className="reviewer-meta">Status: {workflowStatusLabel(assignment.manuscript_status)}</p>}

                    <p className="reviewer-meta">
                      Assignment #{assignmentId}
                    </p>
                    <p className="reviewer-meta">Invitation: {assignment.invitation_status === "legacy" ? "Existing assignment" : workflowStatusLabel(assignment.invitation_status)}</p>
                    <h4>Review documents{Number.isInteger(assignment.review_round) && assignment.review_round > 0 ? ` · Round ${assignment.review_round}` : !(['accepted', 'legacy'].includes(assignment.invitation_status) && ['assigned', 'completed'].includes(assignment.status)) ? ' · Round unavailable' : ''}</h4>
                    <p className="reviewer-meta"><strong>Documents received:</strong> availability is checked for this assignment. Access does not establish when a document was received.</p>
                    <p className="reviewer-meta">Review comments and recommendations are submitted separately from reviewed documents.</p>
                    <h4>Current Stage Actions</h4>
                    {invitationPending && <div><p>Respond to this invitation before accessing the review file.</p><button type="button" disabled={submittingId !== null} onClick={() => respondInvitation(assignmentId, "accept")}>Accept review invitation</button> <button type="button" disabled={submittingId !== null} onClick={() => respondInvitation(assignmentId, "decline")}>Decline review invitation</button></div>}
                    {invitationDeclined && <p>Review invitation declined.</p>}

                    {isAssigned && <button type="button" onClick={() => openDetails(assignment)}>View manuscript details</button>}
                    {isAssigned && details[assignmentId] && <div aria-label="Manuscript details">
                      {details[assignmentId].author_name && <p>Author: {details[assignmentId].author_name}</p>}
                      {details[assignmentId].author_id != null && <p>Author ID: {details[assignmentId].author_id}</p>}
                      {!details[assignmentId].author_name && details[assignmentId].author_id == null && <p>No additional author information is available.</p>}
                    </div>}

                    {assignment.assigned_at && <p className="reviewer-meta">
                      Assigned:{" "}
                      {new Date(
                        assignment.assigned_at
                      ).toLocaleDateString()}
                    </p>}

                    {(invitationPending || invitationDeclined) ? null : assignment.review_file_available === true ? (
                      <button
                        type="button"
                        className="reviewer-download"
                        disabled={downloadingIds.has(assignmentId)}
                        onClick={() =>
                          handleDownload(assignmentId, assignment.review_file_available === true)
                        }
                      >
                        {downloadingIds.has(assignmentId)
                          ? "Downloading..."
                          : "Download Review File"}
                      </button>
                    ) : (
                      <p className="reviewer-meta">Review file unavailable. Contact the editorial team.</p>
                    )}

                    {isAssigned && <ReviewerDocumentUpload key={`upload-${assignmentId}`} token={token} assignmentId={assignmentId} onSaved={()=>setDocumentRevision(value=>value+1)} />}
                    {assignment.invitation_status === 'accepted' && ['assigned','completed'].includes(assignment.status) && <ReviewerDocumentHistory key={`history-${assignmentId}`} token={token} assignmentId={assignmentId} revision={documentRevision} />}
                    {isAssigned && (
                      <div className="review-form" id={`review-action-${assignmentId}`}>
                        <p>Pending review</p>
                        <h4>Submit Review</h4>

                        <label htmlFor={`comments-${assignmentId}`}>
                          Review Comments
                        </label>

                        <textarea
                          id={`comments-${assignmentId}`}
                          rows={4}
                          placeholder="Enter your review comments..."
                          value={review.comments || ""}
                          disabled={submittingId !== null}
                          onChange={(event) =>
                            handleReviewChange(
                              assignmentId,
                              "comments",
                              event.target.value
                            )
                          }
                        />

                        <label
                          htmlFor={`recommendation-${assignmentId}`}
                        >
                          Recommendation
                        </label>

                        <select
                          id={`recommendation-${assignmentId}`}
                          value={review.recommendation || ""}
                          disabled={submittingId !== null}
                          onChange={(event) =>
                            handleReviewChange(
                              assignmentId,
                              "recommendation",
                              event.target.value
                            )
                          }
                        >
                          <option value="">
                            Select recommendation
                          </option>

                          <option value="accept">
                            Accept
                          </option>

                          <option value="revision">
                            Revision
                          </option>

                          <option value="reject">
                            Reject
                          </option>
                        </select>

                        <button
                          type="button"
                          className="reviewer-submit"
                          disabled={submittingId !== null}
                          onClick={() =>
                            handleSubmitReview(assignmentId)
                          }
                        >
                          {isSubmitting
                            ? "Submitting..."
                            : "Submit Review"}
                        </button>
                      </div>
                    )}

                    {isCompleted && (
                      <section aria-label="Review History">
                        <h4>Review History</h4>
                        <p className="reviewer-completed-message">Review already submitted.</p>
                        {ownReview?.token === token && ownReview.assignmentId === assignmentId && ownReview.manuscriptId === assignment.manuscript_id && ownReview.round === assignment.review_round ? (
                          ownReview.loading ? <p role="status">Loading submitted review…</p> : ownReview.error ? <p>Submitted review is unavailable.</p> : ownReview.data && <div>
                            <h5>Submitted Review · Round {ownReview.round}</h5>
                            <p><strong>Recommendation:</strong> {ownReview.data.recommendation}</p>
                            <p><strong>Comments:</strong> {ownReview.data.comments}</p>
                            <p><strong>Submitted:</strong> {Number.isNaN(Date.parse(ownReview.data.submitted_at)) ? 'Unavailable' : new Date(ownReview.data.submitted_at).toLocaleString()}</p>
                          </div>
                        ) : <p role="status">Loading submitted review…</p>}
                      </section>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
        </div>
        </div>
      </main>
    </div>
  );
}

export default function ReviewerDashboard(props) {
  const id = props.user?.user_id;
  if (!Number.isSafeInteger(id) || id < 1) return <main role="alert">Reviewer account unavailable. Sign in again.</main>;
  return <ReviewerWorkspace key={id} {...props} />;
}
