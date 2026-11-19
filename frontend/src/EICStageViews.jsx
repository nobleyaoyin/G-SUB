// Stage views contain presentation and call existing parent-owned action handlers.
// They do not create workflow transitions on navigation.
export function InitialScreeningStageView({ selected, decision, comments, setDecision, setComments, act, busy, needsRefresh }) {
  return (
            <section className="eic-action-card">
              <div className="eic-action-card-heading">
                <span>01</span>
                <h4>Initial Screening</h4>
              </div>
              <p>Evaluate the newly submitted manuscript.</p>
              <form onSubmit={e => {
                e.preventDefault();
                act(`/eic/manuscripts/${selected}/initial-scan`, { decision, comments });
              }}>
                <label>Decision
                  <select required value={decision} onChange={e => setDecision(e.target.value)}>
                    <option value="">Choose</option>
                    <option value="pass">Pass</option>
                    <option value="revision_required">Request revision</option>
                    <option value="reject">Reject</option>
                  </select>
                </label>
                <label>Comments
                  <textarea required maxLength="5000" value={comments}
                    onChange={e => setComments(e.target.value)} />
                </label>
                <button disabled={busy || needsRefresh}>Record screening</button>
              </form>
            </section>
  );
}

export function EICDecisionStageView({ selected, round, decision, comments, setDecision, setComments, act, busy, needsRefresh }) {
  return (
            <section className="eic-action-card eic-decision-card">
              <div className="eic-action-card-heading">
                <span>05</span>
                <h4>Editorial Decision</h4>
              </div>
              <p>Make the editorial decision for review round {round}.</p>
              <form onSubmit={e => {
                e.preventDefault();
                act(`/eic/manuscripts/${selected}/decision`, { decision, comments });
              }}>
                <label>Decision
                  <select required value={decision} onChange={e => setDecision(e.target.value)}>
                    <option value="">Choose</option>
                    <option value="accept">Accept</option>
                    <option value="revision_required">Request revision</option>
                    <option value="reject">Reject</option>
                  </select>
                </label>
                <label>Comments
                  <textarea required maxLength="5000" value={comments}
                    onChange={e => setComments(e.target.value)} />
                </label>
                <button disabled={busy || needsRefresh}>Record editorial decision</button>
              </form>
            </section>
  );
}

export function InitialEditorAssignmentView({ selected, editor, setEditor, editors, act, busy, needsRefresh }) {
  return (
            <section className="eic-action-card">
              <div className="eic-action-card-heading">
                <span>02</span>
                <h4>Initial Editor Assignment</h4>
              </div>
              <p>Assign an editor to begin initial manuscript editing.</p>
              <form onSubmit={e => {
                e.preventDefault();
                act("/eic/initial-editor/invite", {
                  manuscript_id: selected,
                  editor_id: Number(editor)
                });
              }}>
                <label>Editor
                  <select required value={editor} onChange={e => setEditor(e.target.value)}>
                    <option value="">Choose editor</option>
                    {editors.map(x => (
                      <option value={x.user_id} key={x.user_id}>{x.name}</option>
                    ))}
                  </select>
                </label>
                <button disabled={busy || needsRefresh}>Send invitation</button>
              </form>
            </section>
  );
}

export function InitialEditingReviewView({ submission, decision, comments, setDecision, setComments, act, busy, needsRefresh }) {
  return (
            <section className="eic-action-card" >
              <div className="eic-action-card-heading">
                <span>03</span>
                <h4>Initial Editing Review</h4>
              </div>
              <p>Review submission #{submission.submission_id}.</p>
              <form onSubmit={e => {
                e.preventDefault();
                act(`/eic/initial-editing/submissions/${submission.submission_id}/eic-approval`, {
                  decision, comments
                });
              }}>
                <label>Decision
                  <select required value={decision} onChange={e => setDecision(e.target.value)}>
                    <option value="">Choose</option>
                    <option value="approve">Approve</option>
                    <option value="request_revision">Request revision</option>
                  </select>
                </label>
                <label>Comments
                  <textarea required maxLength="5000" value={comments}
                    onChange={e => setComments(e.target.value)} />
                </label>
                <button disabled={busy || needsRefresh}>Record editing decision</button>
              </form>
            </section>
  );
}

export function PeerReviewStageView({ overview }) {
  return (
            <section className="eic-action-card eic-progress-card">
              <div className="eic-action-card-heading">
                <span>04</span>
                <h4>Peer Review Progress</h4>
              </div>
              <div className="eic-review-progress-number">
                {overview.review_progress?.completed_distinct ?? "Unavailable"}
                <span> / {overview.review_progress?.required ?? "Unavailable"}</span>
              </div>
              <p>Completed distinct reviewers</p>
              <p>This decision-policy count may differ from the stricter recommendation eligibility count below.</p>
              {overview.review_progress?.policy === "legacy" &&
                <p>Historical review rule applies.</p>}
              {overview.review_progress?.blocked_reason &&
                <p className="eic-action-warning">
                  Decision blocked: {overview.review_progress.blocked_reason}
                </p>}
            </section>
  );
}

export function FinalEditorAssignmentView({ selected, editor, setEditor, editors, act, busy, needsRefresh }) {
  return (
              <section className="eic-action-card">
                <div className="eic-action-card-heading">
                  <span>06</span>
                  <h4>Final Editor Assignment</h4>
                </div>
                <p>Assign an editor for final manuscript editing.</p>
                <form onSubmit={e => {
                  e.preventDefault();
                  act('/final-workflow/invite', {
                    manuscript_id: selected,
                    editor_id: Number(editor)
                  });
                }}>
                  <label>Editor
                    <select required value={editor} onChange={e => setEditor(e.target.value)}>
                      <option value="">Choose editor</option>
                      {editors.map(x => (
                        <option value={x.user_id} key={x.user_id}>{x.name}</option>
                      ))}
                    </select>
                  </label>
                  <button disabled={busy || needsRefresh}>Send final editor invitation</button>
                </form>
              </section>
  );
}

export function FinalEditingReviewView({ latestFinal, decision, comments, setDecision, setComments, act, busy, needsRefresh }) {
  return (
            <section className="eic-action-card">
              <div className="eic-action-card-heading">
                <span>07</span>
                <h4>Final Editing Review</h4>
              </div>
              <p>Review final edit #{latestFinal.submission_id}.</p>
              <form onSubmit={e => {
                e.preventDefault();
                act(`/final-workflow/submissions/${latestFinal.submission_id}/eic-review`, {
                  decision, comments
                });
              }}>
                <label>Decision
                  <select required value={decision} onChange={e => setDecision(e.target.value)}>
                    <option value="">Choose</option>
                    <option value="approve">Approve</option>
                    <option value="request_revision">Request corrections</option>
                  </select>
                </label>
                <label>Comments
                  <textarea required maxLength="5000" value={comments}
                    onChange={e => setComments(e.target.value)} />
                </label>
                <button disabled={busy || needsRefresh}>Submit final edit review</button>
              </form>
            </section>
  );
}
