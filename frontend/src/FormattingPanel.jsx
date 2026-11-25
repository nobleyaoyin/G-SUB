import {displayError} from './displayError';
import './ManuscriptsListLayout.css';
import {workflowStatusLabel} from './workflowStatus';
import useStageProjection, {StageProjectionNotice} from './useStageProjection';
import RoleStatistics from './RoleStatistics';
import RoleListControls, { selectRoleItems } from "./RoleListControls";
import RoleOverview from "./RoleOverview";
import ManuscriptTimeline from "./ManuscriptTimeline";
import useManuscriptReturn from "./useManuscriptReturn";
import useReturnRefresh from "./useReturnRefresh";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, actionFailureMessage, submitAction } from "./api";
import "./InitialEditingPanel.css";
import "./FormattingPanel.css";
import ManuscriptProgress from "./ManuscriptProgress";
import { formatterPrompt } from "./participantPrompts";
import NotesPanel from "./NotesPanel";
import GeneralCommentsPanel from "./GeneralCommentsPanel";

export default function FormattingPanel({
  role, token, manuscriptId, canInvite = false, showProgress = true,
  onChanged, navigationTarget, onDirtyChange, registerManuscriptReturn, section, onSectionChange
}) {
  const [listSearch, setListSearch] = useState("");
  const [listStatus, setListStatus] = useState("");
  const [listSort, setListSort] = useState("recent");
  const [items, setItems] = useState([]);
  const [formatterProgressTask, setFormatterProgressTask] = useState(null);
  const [itemsScope, setItemsScope] = useState(null);
  const [people, setPeople] = useState([]);
  const [choice, setChoice] = useState("");
  const [selectedItem, setSelectedItem] = useState(null);
  const downloadScope = useRef({ token, role, manuscriptId, selectedItem, mounted: true });
  if (downloadScope.current.token !== token || downloadScope.current.role !== role ||
      downloadScope.current.manuscriptId !== manuscriptId || downloadScope.current.selectedItem !== selectedItem) {
    downloadScope.current = { token, role, manuscriptId, selectedItem, mounted: true };
  }
  useEffect(() => { downloadScope.current.mounted = true; return () => { downloadScope.current.mounted = false; }; }, []);
  const lastNavigation = useRef(null);
  const [progressRevision, setProgressRevision] = useState(0);
  const receiveFormatterProgress = useCallback(data => {
    setFormatterProgressTask(data ? { token, revision:progressRevision, scope:downloadScope.current, manuscriptId:data.manuscript_id, task:data.participant_task, stage:data.current_stage } : null);
  }, [token, progressRevision]);
  const [comments, setComments] = useState("");
  const [decision, setDecision] = useState("");
  const [file, setFile] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [noteDirty, setNoteDirty] = useState(false);
  const [staffCommentDirty, setStaffCommentDirty] = useState(false);
  const requestSequence = useRef(0);
  const requestScope = useRef({ token, role, manuscriptId, generation: 0 });
  if (requestScope.current.token !== token || requestScope.current.role !== role || requestScope.current.manuscriptId !== manuscriptId) {
    requestScope.current = { token, role, manuscriptId, generation: requestScope.current.generation + 1 };
  }

  useEffect(() => {
    setSelectedItem(null);
    setComments(""); setDecision(""); setFile(null); setChoice("");
    setError(""); setMessage("");
    lastNavigation.current = null;
  }, [token, role, manuscriptId]);

  const formattingDirty = Boolean(comments || decision || file || choice || noteDirty || staffCommentDirty);
  const onDirtyChangeRef = useRef(onDirtyChange);

  useEffect(() => {
    onDirtyChangeRef.current = onDirtyChange;
  }, [onDirtyChange]);

  useEffect(() => {
    onDirtyChangeRef.current?.(formattingDirty);
  }, [formattingDirty]);

  useEffect(() => {
    return () => onDirtyChangeRef.current?.(false);
  }, []);

  useManuscriptReturn(registerManuscriptReturn, () => {
    if (manuscriptId != null) return true;
    if (formattingDirty && !window.confirm("Discard unsaved formatting changes?")) return false;
    setComments(""); setDecision(""); setFile(null); setChoice(""); setSelectedItem(null);
    return true;
  });

  const request = useCallback(async (path, options = {}) => {
    const r = await fetch(`${API_URL}/formatting${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${token}`,
        ...options.headers
      }
    });
    if (!r.ok) {
      const b = await r.json().catch(() => ({}));
      throw new Error(b.detail || `Request failed (${r.status})`);
    }
    return r.json();
  }, [token]);

  const load = useCallback(async () => {
    const scope = requestScope.current;
    const sequence = ++requestSequence.current;
    const current = () => requestScope.current === scope && requestSequence.current === sequence;
    try {
      if (role === "eic") {
        if (!manuscriptId) return false;
        const [item, formatters] = await Promise.all([
          request(`/manuscripts/${manuscriptId}`), request("/formatters")
        ]);
        if (!current() || item?.manuscript_id !== manuscriptId) return false;
        setItems([item]);
        setItemsScope(scope);
        setPeople(formatters);
      } else {
        const result = await request("/my");
        if (!current()) return false;
        setItems(result);
        setItemsScope(scope);
      }
      setProgressRevision(v => v + 1);
      return true;
    } catch (error) {
      if (!current()) return false;
      throw error;
    }
  }, [role, manuscriptId, request]);

  useEffect(() => {
    let active = true;
    setItems([]);
    setPeople([]);
    load().catch(e => { if (active) setError(e.message); });
    return () => { active = false; requestSequence.current += 1; };
  }, [load]);

  const safeItems = itemsScope === requestScope.current ? items : [];

  useEffect(() => {
    const target = navigationTarget?.manuscriptId;
    if (
      (role !== "formatter" && role !== "editor") ||
      target == null ||
      navigationTarget === lastNavigation.current ||
      !safeItems.some(item => item.manuscript_id === target)
    ) return;

    lastNavigation.current = navigationTarget;
    if (target === selectedItem) return;

    if (formattingDirty &&
        !window.confirm("Discard unsaved formatting changes?")) return;

    setComments("");
    setDecision("");
    setFile(null);
    setSelectedItem(target);
  }, [navigationTarget, role, items, itemsScope, selectedItem, formattingDirty]);

  useReturnRefresh(
    () => load()
      .then(loaded => {
        if (loaded) { setNeedsRefresh(false); setError(""); }
      })
      .catch(e => setError(e.message)),
    busy || (!needsRefresh && Boolean(comments || decision || file || choice))
  );

  const action = async (path, data) => {
    if (busy || needsRefresh) return;
    const expected = downloadScope.current;
    const current = () => expected.mounted && downloadScope.current === expected;
    setBusy(true);
    setError("");
    setMessage("");

    try {
      const form = data instanceof FormData;
      await submitAction(`${API_URL}/formatting${path}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          ...(form ? {} : { "Content-Type": "application/json" })
        },
        body: form ? data : JSON.stringify(data)
      });
      if (!current()) return;
      setMessage("Action completed.");
      setComments("");
      setDecision("");
      setFile(null);
      try {
        const loaded = await load();
        if (!current() || !loaded) return;
        if (onChanged && await onChanged() === false) throw new Error("View changed");
      } catch {
        if (current()) {
          setNeedsRefresh(true);
          setError("Action saved, but the latest state could not be loaded. Return to this view; do not repeat the action.");
        }
      }
    } catch (e) {
      if (current()) {
        setError(actionFailureMessage(e));
        if (!e.confirmedRejection) setNeedsRefresh(true);
      }
    } finally {
      if (downloadScope.current.mounted) setBusy(false);
    }
  };

  const download = async path => {
    const expected = downloadScope.current;
    const current = () => expected.mounted && downloadScope.current === expected;
    try {
      const r = await fetch(`${API_URL}/formatting${path}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!r.ok) throw new Error("File unavailable");

      const blob = await r.blob();
      if (!current()) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;

      const type = r.headers.get("content-type") || "";
      const ext = type.startsWith("text/plain") ? ".txt"
        : type.includes("wordprocessingml") ? ".docx"
        : type.includes("msword") ? ".doc" : ".pdf";

      a.download =
        (r.headers.get("content-disposition") || "")
          .match(/filename="?([^";]+)"?/)?.[1] || `formatting${ext}`;

      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      if (current()) setError(e.message);
    }
  };

  const visibleItems = manuscriptId == null
    ? safeItems
    : safeItems.filter(item => item.manuscript_id === manuscriptId);

  const stageProjection = useStageProjection(visibleItems, token, role === "formatter" ? listStatus : "");

  if (
    (role === "editor" || role === "formatter") &&
    manuscriptId != null &&
    visibleItems.length === 0 && !error && !message
  ) return null;

  if (
    role !== "formatter" && role !== "editor" &&
    visibleItems.length === 0 && !error && !message
  ) return null;

  if (
    role === "eic" && !error && !message && !canInvite &&
    visibleItems.length > 0 &&
    visibleItems.every(item =>
      !["formatting", "published"].includes(item.status) &&
      !item.invitations?.length &&
      !item.submissions?.length &&
      !item.publication
    )
  ) return null;

  const formatterMode = role === "formatter" || role === "editor";

  if (role === 'formatter' && section === 'dashboard') {
    return <RoleOverview label="Formatter" items={safeItems} loading={itemsScope !== requestScope.current} error={displayError(error)} onNavigate={onSectionChange} onOpen={item => { setSelectedItem(item.manuscript_id); onSectionChange('manuscripts'); }} />;
  }

  if (formatterMode && manuscriptId == null && selectedItem === null) {
    return (
      <section
        className={`initial-editing-panel formatting-workflow ${
          (role === "formatter" || role === "editor") ? "formatter-dashboard" : ""
        }`}
        aria-label="Formatting workflow"
        data-sidebar-target="manuscripts"
      >
        <div className={role === "formatter" && section === "manuscripts" ? "manuscripts-list-layout" : undefined}>
        <div className={role === "formatter" && section === "manuscripts" ? "manuscripts-list-content" : undefined}>
        <h2>{(role === "formatter" || role === "editor") ? "Formatting Dashboard" : "Manuscripts"}</h2>
        {error && <p role="alert">{displayError(error)}</p>}
        {role === "formatter" && section === "manuscripts" && <StageProjectionNotice projection={stageProjection} />}
        {role === "formatter" && section === "manuscripts" && <RoleListControls projection={stageProjection} items={stageProjection.items} search={listSearch} setSearch={setListSearch} status={listStatus} setStatus={setListStatus} sort={listSort} setSort={setListSort} />}
        {role === "formatter" && section === "manuscripts" && visibleItems.length > 0 && (listSearch || listStatus) && !stageProjection.loading && !stageProjection.unavailable && selectRoleItems(stageProjection.items, listSearch, listStatus, listSort).length === 0 && <p>No manuscripts match the current filters.</p>}
        {visibleItems.length === 0 ? (
          <p>No formatting assignments.</p>
        ) : (
          <div className="formatter-manuscript-list">
            {(role === "formatter" && section === "manuscripts" ? selectRoleItems(stageProjection.items, listSearch, listStatus, listSort) : visibleItems).map(item => (
              <article className="initial-editing-item" key={item.manuscript_id}>
                {manuscriptId == null && <h3>{item.title?.trim() ? `#${item.manuscript_id} ${item.title}` : `Manuscript #${item.manuscript_id}`}</h3>}
                <p>{workflowStatusLabel(item.status)}</p>
                <button
                  type="button"
                  onClick={() => setSelectedItem(item.manuscript_id)}
                >
                  Open manuscript
                </button>
              </article>
            ))}
          </div>
        )}
        </div>
        {role === "formatter" && section === "manuscripts" && <aside className="manuscripts-list-sidebar" aria-label="Manuscript statistics"><RoleStatistics items={safeItems} label="Formatting assignments" loading={itemsScope !== requestScope.current} error={displayError(error)} /></aside>}
        </div>
      </section>
    );
  }

  const renderFormatter = item => {
    const active = item.invitations.find(i =>
      ["pending", "accepted"].includes(i.status)
    );
    const latest = item.submissions[0];
    const currentTask = formatterProgressTask?.token === token && formatterProgressTask?.revision === progressRevision &&
      formatterProgressTask?.scope === downloadScope.current && formatterProgressTask?.manuscriptId === item.manuscript_id &&
      formatterProgressTask?.task?.relevant_stage === formatterProgressTask?.stage && !needsRefresh && !error
      ? formatterProgressTask.task : null;

    return (
      <article className="formatter-manuscript-card" key={item.manuscript_id}>
        <header className="formatter-manuscript-header">
          {manuscriptId == null && <div><h3>{item.title?.trim() || `Manuscript #${item.manuscript_id}`}</h3>{item.title?.trim() && <p className="formatter-manuscript-id">Manuscript #{item.manuscript_id}</p>}</div>}
          <span className="formatter-status">
            {workflowStatusLabel(item.status)}
          </span>
        </header>

        {role === 'formatter' && manuscriptId == null && active?.status === 'accepted' && <div key={`${token}-${item.manuscript_id}`}>
          <details className="formatter-collapsible"><summary>Private Notes</summary><NotesPanel manuscriptId={item.manuscript_id} token={token} onDirtyChange={setNoteDirty} /></details>
          <details className="formatter-collapsible"><summary>Comments (Staff Shared)</summary><GeneralCommentsPanel manuscriptId={item.manuscript_id} token={token} onDirtyChange={setStaffCommentDirty} /></details>
        </div>}

        {manuscriptId == null && active?.status === 'accepted' && <ManuscriptTimeline manuscriptId={item.manuscript_id} token={token} revision={progressRevision} />}
        {(showProgress || active?.status !== "accepted") && <section className="formatter-progress-section">
          {active?.status === "accepted" ? (showProgress &&
            <ManuscriptProgress showTitle={false} showNextAction={false}
              key={`${item.manuscript_id}-${progressRevision}`}
              manuscriptId={item.manuscript_id}
              token={token}
              onProgressChange={receiveFormatterProgress}
            />
          ) : (
            <p>Progress is available after the invitation is accepted.</p>
          )}
        </section>}
        <p><strong>Next action:</strong> {currentTask && ['action_required','waiting','no_action'].includes(currentTask.task_state) && typeof currentTask.task_message === 'string' ? currentTask.task_message : formatterPrompt(item, needsRefresh || Boolean(error))}{currentTask?.task_state === 'action_required' && ['Formatting', 'Proofing'].includes(currentTask.relevant_stage) && currentTask.action_label === 'View formatting actions' && currentTask.permitted_action_target === `#formatting-action-${item.manuscript_id}` && active?.status === 'accepted' && item.status === 'formatting' && <> <a href={currentTask.permitted_action_target}>{currentTask.action_label}</a></>}</p>

        <details className="formatter-collapsible">
          <summary>Manuscript Information</summary>
          <div className="formatter-section-content">
            <p>
              <strong>Manuscript status:</strong>{" "}
              {workflowStatusLabel(item.status)}
            </p>
            {item.publication && (
              <p>
                Local publication prototype · DOI pending external registration
                · published {new Date(item.publication.published_at).toLocaleString()}
                · approved file #{item.publication.submission_id}
              </p>
            )}
            {item.invitations.map(i => (
              <p key={i.invitation_id}>{i.formatter} — {workflowStatusLabel(i.status)}</p>
            ))}
          </div>
        </details>

        {item.submissions.length > 0 && (
          <details className="formatter-collapsible formatter-history">
            <summary>
              <span>Formatting History</span>
              <span className="formatter-history-count">
                {item.submissions.length} {item.submissions.length === 1 ? "version" : "versions"}
              </span>
            </summary>

            <div className="formatter-section-content">
              {item.submissions.map((s, index) => (
                <article className="formatter-history-item" key={s.submission_id}>
                  <div className="formatter-history-heading">
                    <div>
                      <h4>Submission #{s.submission_id}</h4>
                      <p className="formatter-history-date">
                        Submitted: {s.created_at
                          ? new Date(s.created_at).toLocaleString()
                          : "Not available"}
                      </p>
                    </div>

                    <div className="formatter-history-badges">
                      {index === 0 && (
                        <span className="formatter-latest-badge">Latest</span>
                      )}
                      <span className={`formatter-history-status ${s.status}`}>
                        {workflowStatusLabel(s.status)}
                      </span>
                    </div>
                  </div>

                  <div className="formatter-review-block">
                    <h5>Formatter Comments</h5>
                    <p>{s.comments || "No comments provided."}</p>
                  </div>

                  <div className="formatter-review-block">
                    <div className="formatter-review-heading">
                      <h5>Author Review</h5>
                      <span className="formatter-review-date">
                        {s.author_reviewed_at
                          ? new Date(s.author_reviewed_at).toLocaleString()
                          : "Not reviewed yet"}
                      </span>
                    </div>
                    <p>{s.author_comments || "No author comments."}</p>
                  </div>

                  <div className="formatter-review-block">
                    <div className="formatter-review-heading">
                      <h5>EIC Review</h5>
                      <span className="formatter-review-date">
                        {s.eic_reviewed_at
                          ? new Date(s.eic_reviewed_at).toLocaleString()
                          : "Not reviewed yet"}
                      </span>
                    </div>
                    <p>{s.eic_comments || "No EIC comments."}</p>
                  </div>

                  <button
                    type="button"
                    className="formatter-download-button"
                    onClick={() => download(`/submissions/${s.submission_id}/download`)}
                  >
                    Download formatted file
                  </button>
                </article>
              ))}
            </div>
          </details>
        )}

        <section className="formatter-actions" id={`formatting-action-${item.manuscript_id}`}>
          <h4>Formatting Actions</h4>

          {active?.status === "pending" && (
            <div className="formatter-invitation-actions">
              <p>You have received a formatting invitation.</p>
              <button
                disabled={busy || needsRefresh}
                onClick={() => action(
                  `/invitations/${active.invitation_id}/respond`,
                  { decision: "accept" }
                )}
              >
                Accept formatting invitation
              </button>
              <button
                disabled={busy || needsRefresh}
                onClick={() => action(
                  `/invitations/${active.invitation_id}/respond`,
                  { decision: "decline" }
                )}
              >
                Decline formatting invitation
              </button>
            </div>
          )}

          {active?.status === "accepted" && (
            <>
              <button
                className="formatter-download-button"
                onClick={() => download(`/invitations/${active.invitation_id}/input`)}
              >
                Download approved final edit
              </button>

              {item.status === "formatting" &&
                (!latest || latest.status.endsWith("revision_requested")) && (
                  <form
                    className="formatting-proof-form"
                    onSubmit={e => {
                      e.preventDefault();
                      const f = new FormData();
                      f.append("file", file);
                      f.append("comments", comments);
                      action(`/invitations/${active.invitation_id}/submit`, f);
                    }}
                  >
                    <h4>Upload formatted file</h4>
                    <label>
                      PDF, DOCX, DOC, or UTF-8 TXT file
                      <input
                        type="file"
                        accept=".pdf,.docx,.doc,.txt"
                        required
                        onChange={e => setFile(e.target.files[0])}
                      />
                    </label>
                    <label>
                      Comments
                      <textarea
                        required
                        value={comments}
                        onChange={e => setComments(e.target.value)}
                      />
                    </label>
                    <button type="submit" disabled={busy || needsRefresh || !file}>
                      Submit formatted file
                    </button>
                  </form>
                )}
            </>
          )}

          {!active && <p>No active formatting invitation.</p>}
          {active?.status === "accepted" && item.status !== "formatting" && (
            <p>No upload action is currently available for this manuscript status.</p>
          )}
        </section>
      </article>
    );
  };

  const renderExisting = item => {
    const active = item.invitations.find(i =>
      ["pending", "accepted"].includes(i.status)
    );
    const latest = item.submissions[0];

    return (
      <article className="initial-editing-item" key={item.manuscript_id}>
        {manuscriptId == null && <h3>{item.title?.trim() ? `#${item.manuscript_id} ${item.title}` : `Manuscript #${item.manuscript_id}`}</h3>}

        {role === "editor" && showProgress && (
          active?.status === "accepted" ? (
            <ManuscriptProgress showTitle={false} showNextAction={false}
              key={`${item.manuscript_id}-${progressRevision}`}
              manuscriptId={item.manuscript_id}
              token={token}
            />
          ) : <p>Progress is available after the invitation is accepted.</p>
        )}

        {role === "editor" && <h4>Manuscript Information</h4>}
        <p>Manuscript: {workflowStatusLabel(item.status)}</p>

        {item.publication && (
          <p>
            Local publication prototype · DOI pending external registration
            · published {new Date(item.publication.published_at).toLocaleString()}
            · approved file #{item.publication.submission_id}
          </p>
        )}

        {item.invitations.map(i => (
          <p key={i.invitation_id}>{i.formatter} — {workflowStatusLabel(i.status)}</p>
        ))}

        {role === "eic" && !active &&
          (item.status === "formatting" || (item.status === "final_editing" && canInvite)) && (
            <form onSubmit={e => {
              e.preventDefault();
              action("/invite", {
                manuscript_id: item.manuscript_id,
                formatter_id: Number(choice)
              });
            }}>
              <h4>Assign Editor for Formatting</h4>
              <label>
                Editor
                <select required value={choice} onChange={e => setChoice(e.target.value)}>
                  <option value="">Choose editor</option>
                  {people.map(p => (
                    <option key={p.user_id} value={p.user_id}>{p.name}</option>
                  ))}
                </select>
              </label>
              <button disabled={busy || needsRefresh}>Send editor invitation</button>
              <p>Requires an EIC-approved and author-confirmed final edit.</p>
            </form>
          )}

        {role === "editor" && active?.status === "pending" && (
          <div>
            <button disabled={busy || needsRefresh} onClick={() =>
              action(`/invitations/${active.invitation_id}/respond`, { decision: "accept" })
            }>Accept formatting invitation</button>
            <button disabled={busy || needsRefresh} onClick={() =>
              action(`/invitations/${active.invitation_id}/respond`, { decision: "decline" })
            }>Decline formatting invitation</button>
          </div>
        )}

        {role === "editor" && active?.status === "accepted" && (
          <>
            <button onClick={() => download(`/invitations/${active.invitation_id}/input`)}>
              Download approved final edit
            </button>
            {item.status === "formatting" &&
              (!latest || latest.status.endsWith("revision_requested")) && (
                <form className="formatting-proof-form" onSubmit={e => {
                  e.preventDefault();
                  const f = new FormData();
                  f.append("file", file);
                  f.append("comments", comments);
                  action(`/invitations/${active.invitation_id}/submit`, f);
                }}>
                  <h4>Upload formatted file</h4>
                  <label>
                    PDF, DOCX, DOC, or UTF-8 TXT file
                    <input type="file" accept=".pdf,.docx,.doc,.txt" required
                      onChange={e => setFile(e.target.files[0])} />
                  </label>
                  <label>
                    Comments
                    <textarea required value={comments}
                      onChange={e => setComments(e.target.value)} />
                  </label>
                  <button disabled={busy || needsRefresh || !file}>
                    Submit formatted file
                  </button>
                </form>
              )}
          </>
        )}

        {item.submissions.map(s => (
          <div key={s.submission_id}>
            <p>Formatted #{s.submission_id} · {workflowStatusLabel(s.status)} · {s.comments}</p>
            <p>Author: {s.author_comments || "—"} · EIC: {s.eic_comments || "—"}</p>
            <button onClick={() => download(`/submissions/${s.submission_id}/download`)}>
              Download formatted file
            </button>
          </div>
        ))}

        {latest &&
          ((role === "author" && latest.status === "pending_author") ||
           (role === "eic" && latest.status === "pending_eic")) && (
            <form onSubmit={e => {
              e.preventDefault();
              action(`/submissions/${latest.submission_id}/${role}-review`, {
                decision, comments
              });
            }}>
              <h4>{role === "author" ? "Review formatting" : "Check author formatting review"}</h4>
              <label>
                Decision
                <select required value={decision} onChange={e => setDecision(e.target.value)}>
                  <option value="">Choose</option>
                  <option value="approve">Approve</option>
                  <option value="request_revision">Request corrections</option>
                </select>
              </label>
              <label>
                Comments
                <textarea required value={comments} onChange={e => setComments(e.target.value)} />
              </label>
              <button disabled={busy || needsRefresh}>Submit formatting review</button>
            </form>
          )}

        {role === "eic" && latest?.status === "approved" && !item.publication && (
          <button disabled={busy || needsRefresh}
            onClick={() => action(`/submissions/${latest.submission_id}/publish`, {})}>
            Publish local prototype
          </button>
        )}

        {role === "editor" ? <p><strong>{manuscriptId == null ? "Next action:" : "Formatting guidance:"}</strong> {formatterPrompt(item, needsRefresh || Boolean(error))}</p> : role !== "eic" && !item.publication && (
          <p>
            Next: {!active ? "EIC assigns an Editor for formatting"
              : active.status === "pending" ? "Editor responds"
              : !latest || latest.status.endsWith("revision_requested")
                ? "Editor uploads a PDF, DOCX, DOC, or UTF-8 TXT file"
                : latest.status === "pending_author" ? "author reviews formatting"
                : latest.status === "pending_eic" ? "EIC checks author review"
                : "EIC may publish the local prototype"}
          </p>
        )}
      </article>
    );
  };

  const formatterDetail = role === "formatter" && manuscriptId == null && selectedItem !== null;
  const workspaceContent = <>
      <div className="initial-editing-heading">
        <h2>{(role === "formatter" || role === "editor") ? "Formatting Dashboard" : "Formatting and local publication"}</h2>
      </div>

      {formatterMode && manuscriptId == null && (
        <button type="button" className="manuscript-back" onClick={() => {
          if ((comments || decision || file) &&
              !window.confirm("Discard unsaved formatting changes?")) return;
          setComments("");
          setDecision("");
          setFile(null);
          setSelectedItem(null);
        }}>
          Back to manuscripts
        </button>
      )}

      {error && <p role="alert">{displayError(error)}</p>}
      {message && <p role="status">{message}</p>}
      {visibleItems.length === 0 && <p>No formatting assignments.</p>}

      {visibleItems
        .filter(item => !formatterMode || item.manuscript_id === (manuscriptId ?? selectedItem))
        .map(item => (role === "formatter" || role === "editor") ? renderFormatter(item) : renderExisting(item))}
  </>;
  return (
    <section
      className={`initial-editing-panel formatting-workflow ${
        (role === "formatter" || role === "editor") ? "formatter-dashboard" : ""
      }`}
      aria-label="Formatting workflow"
      data-workspace={formatterMode && manuscriptId == null && selectedItem !== null ? "selected" : undefined}
      data-sidebar-target={formatterMode ? "manuscripts" : undefined}
    >
      {formatterDetail ? <div className="manuscripts-list-layout">
        <aside className="manuscripts-list-sidebar" aria-label="Manuscript statistics"><RoleStatistics items={safeItems} label="Formatting assignments" loading={itemsScope !== requestScope.current} error={displayError(error)} /></aside>
        <div className="manuscripts-list-content">{workspaceContent}</div>
      </div> : workspaceContent}
    </section>
  );
}
