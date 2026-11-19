import { ReviewerDocumentUpload } from "./DocumentDistribution";
import useManuscriptReturn from "./useManuscriptReturn";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import "./ReviewerDashboard.css";
import NotificationBell from "./NotificationBell";
import ReviewerProfilePanel from "./ReviewerProfilePanel";
import useReturnRefresh from "./useReturnRefresh";
import ManuscriptProgress from "./ManuscriptProgress";
import { reviewerPrompt } from "./participantPrompts";
import { PRODUCT_DISPLAY_NAME, PRODUCT_SYSTEM_NAME } from "./branding";

import { API_URL } from "./api";

function ReviewerWorkspace({ user, token, onProfileDirtyChange, registerManuscriptReturn }) {
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

      // Clear the submitted review form
      setReviews((previous) => {
        const updated = { ...previous };
        delete updated[assignmentId];
        return updated;
      });

      // Reload assignments to show the completed status
      const refreshed = await loadAssignments();

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
      setError(err.message || "Review submission failed.");
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
  useManuscriptReturn(registerManuscriptReturn, () => {
    const review = reviews[selectedId] || {};
    if ((review.comments || review.recommendation) && !window.confirm('Leave this review and discard unsaved changes?')) return false;
    discardReview(selectedId);
    setSelectedId(null);
    return true;
  });

  const handleNotificationNavigate = (notification) => {
    const manuscriptId = notification.manuscript_id;
    const target = assignments.filter(item => item.manuscript_id === manuscriptId)
      .sort((a, b) => b.review_round - a.review_round)[0];
    if (!target) return;
    const current = reviews[selectedId] || {};
    if (selectedId !== null && selectedId !== target.assignment_id && (current.comments || current.recommendation) && !window.confirm('Leave this review and discard unsaved changes?')) return;
    if (selectedId !== target.assignment_id) discardReview(selectedId);
    setSelectedId(target.assignment_id);
  };

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
          />


        </div>

      </header>

      <main className="reviewer-main">
        <h2>Welcome, {user.name}!</h2>

        <p className="reviewer-description">
          Review assigned manuscripts and submit your recommendations.
        </p>

        <div hidden={selectedId !== null}><button type="button" className="reviewer-download" aria-expanded={profileOpen} aria-controls="reviewer-profile-section" onClick={() => {
          if (profileOpen && profileDirty && !window.confirm("Discard unsaved profile changes?")) return;
          if (profileOpen) profileDirtyChanged(false);
          setProfileOpen(value => !value);
        }}>My Professional Profile</button>
        <div id="reviewer-profile-section">{profileOpen && <ReviewerProfilePanel token={token} onDirtyChange={profileDirtyChanged} />}</div>

        <details className="reviewer-collapsible reviewer-stats-collapsible">
          <summary>Statistics</summary>
          <div className="reviewer-stats">
          <div className="reviewer-stat-card">
            <span>Total Assignments</span>
            <strong>{assignments.length}</strong>
          </div>

          <div className="reviewer-stat-card">
            <span>Completed</span>
            <strong>{completedCount}</strong>
          </div>

          <div className="reviewer-stat-card">
            <span>Pending</span>
            <strong>{pendingCount}</strong>
          </div>
          </div>
        </details></div>

        {error && (
          <div className="reviewer-error" role="alert">
            {error}
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

          {loading ? (
            <p>Loading assignments...</p>
          ) : assignments.length === 0 ? (
            <p>No review assignments found.</p>
          ) : (
            <div className="reviewer-list">
              {assignments.filter(assignment => selectedId === null || assignment.assignment_id === selectedId).map((assignment) => {
                const assignmentId = assignment.assignment_id;
                const review = reviews[assignmentId] || {};

                const isCompleted =
                  assignment.status === "completed";

                const isAssigned =
                  assignment.status === "assigned" && ["accepted", "legacy"].includes(assignment.invitation_status);

                const invitationPending = assignment.invitation_status === "pending";
                const invitationDeclined = assignment.invitation_status === "declined";

                if (selectedId === null) return <div id={`assignment-${assignmentId}`} className="reviewer-card" key={assignmentId} data-manuscript-id={assignment.manuscript_id}>
                  <h3>{assignment.manuscript_title || `Manuscript #${assignment.manuscript_id}`}</h3>
                  <p>Manuscript #{assignment.manuscript_id} · Round {assignment.review_round} · {assignment.invitation_status}{assignment.manuscript_status && ` · ${assignment.manuscript_status.replaceAll('_', ' ')}`}</p>
                  <button type="button" onClick={() => setSelectedId(assignmentId)}>Open manuscript</button>
                </div>;

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

                    <button type="button" className="manuscript-back" onClick={() => { if ((review.comments || review.recommendation) && !window.confirm('Leave this review and discard unsaved changes?')) return; discardReview(assignmentId); setSelectedId(null); }}>Back to Manuscripts</button>

                    <div className="reviewer-card-top">
                      <h3>
                        {assignment.manuscript_title?.trim() ||
                          `Manuscript #${assignment.manuscript_id}`}
                      </h3>

                      <span
                        className={`reviewer-status ${assignment.status}`}
                      >
                        {assignment.status}
                      </span>
                    </div>

                    {['accepted', 'legacy'].includes(assignment.invitation_status) && ['assigned', 'completed'].includes(assignment.status)
                      ? <ManuscriptProgress showTitle={false} showNextAction={false} showRound={!(Number.isInteger(assignment.review_round) && assignment.review_round > 0)} key={`${assignment.manuscript_id}-${progressRevision}`} manuscriptId={assignment.manuscript_id} token={token} />
                      : <p>Progress is available after the invitation is accepted.</p>}
                    <p className="reviewer-meta"><strong>Next action:</strong> {reviewerPrompt(assignment, Boolean(error))}</p>
                    <h4>Manuscript Information</h4>

                    {(assignment.manuscript_title?.trim() || assignment.manuscript_status) && <p className="reviewer-meta">
                      {assignment.manuscript_title?.trim() && `Manuscript #${assignment.manuscript_id}`}
                      {assignment.manuscript_status && <>{assignment.manuscript_title?.trim() && ' · '}Status: {assignment.manuscript_status}</>}
                    </p>}

                    <p className="reviewer-meta">
                      Assignment #{assignmentId}
                      {" · "}
                      Review Round {assignment.review_round}
                    </p>
                    <p className="reviewer-meta">Invitation: {assignment.invitation_status === "legacy" ? "existing assignment" : assignment.invitation_status}</p>
                    <h4>Review documents · Round {assignment.review_round ?? "unavailable"}</h4>
                    <p className="reviewer-meta">Incoming manuscript: availability is checked for this assignment. Access does not establish when a document was received.</p>
                    <p className="reviewer-meta">Reviewed document attachment: unavailable in this assignment summary; the review submission contains comments and a recommendation.</p>
                    <h4>Current Stage Actions</h4>
                    {invitationPending && <div><p>Respond to this invitation before accessing the review file.</p><button type="button" disabled={submittingId !== null} onClick={() => respondInvitation(assignmentId, "accept")}>Accept review invitation</button> <button type="button" disabled={submittingId !== null} onClick={() => respondInvitation(assignmentId, "decline")}>Decline review invitation</button></div>}
                    {invitationDeclined && <p>Review invitation declined.</p>}

                    {isAssigned && <button type="button" onClick={() => openDetails(assignment)}>View manuscript details</button>}
                    {isAssigned && details[assignmentId] && <div aria-label="Manuscript details">
                      <p>Manuscript #{details[assignmentId].manuscript_id} · Review round {details[assignmentId].review_round}</p>
                      {details[assignmentId].author_name && <p>Author: {details[assignmentId].author_name}</p>}
                      {details[assignmentId].author_id != null && <p>Author ID: {details[assignmentId].author_id}</p>}
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

                    {isAssigned && <ReviewerDocumentUpload key={assignmentId} token={token} assignmentId={assignmentId} />}
                    {isAssigned && (
                      <div className="review-form">
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
                      <p className="reviewer-completed-message">
                        Review already submitted.
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export default function ReviewerDashboard(props) {
  const id = props.user?.user_id;
  if (!Number.isSafeInteger(id) || id < 1) return <main role="alert">Reviewer account unavailable. Sign in again.</main>;
  return <ReviewerWorkspace key={id} {...props} />;
}
