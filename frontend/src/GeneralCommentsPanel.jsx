import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL } from "./api";
import "./GeneralCommentsPanel.css";

export default function GeneralCommentsPanel({
  manuscriptId,
  token,
  onDirtyChange,
}) {
  const [comments, setComments] = useState([]);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const sectionRef = useRef(null);
  const scope = useRef({manuscriptId, token});
  const sequence = useRef(0);
  if (scope.current.manuscriptId !== manuscriptId || scope.current.token !== token) { scope.current = {manuscriptId, token}; sequence.current++; }
  const [owner, setOwner] = useState(scope.current);
  useEffect(() => {
    if (!error || owner !== scope.current) return;
    const disclosure = sectionRef.current?.closest('details');
    if (!disclosure) return;
    const keepOpen = () => { if (!disclosure.open) disclosure.open = true; };
    keepOpen(); disclosure.addEventListener('toggle', keepOpen);
    return () => disclosure.removeEventListener('toggle', keepOpen);
  }, [error, owner]);
  useEffect(() => { onDirtyChange?.(Boolean(content)); return () => onDirtyChange?.(false); }, [content, onDirtyChange]);

  const loadComments = useCallback(async () => {
    const expected = scope.current, version = ++sequence.current;
    const current = () => scope.current === expected && sequence.current === version;
    setLoading(true);
    setError("");

    try {
      const response = await fetch(
        `${API_URL}/manuscripts/${manuscriptId}/general-comments`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (!response.ok) {
        throw new Error(
          response.status === 403
            ? "You do not have permission to view staff comments."
            : `Unable to load comments (${response.status}).`
        );
      }

      const data = await response.json();
      if (current()) setComments(data);
    } catch (err) {
      if (current()) setError(err.message);
    } finally {
      if (current()) setLoading(false);
    }
  }, [manuscriptId, token]);

  useEffect(() => {
    setOwner(scope.current); setComments([]); setContent(""); setError(""); setSaving(false);
    loadComments();
    return () => { sequence.current++; };
  }, [loadComments]);

  const submitComment = async (event) => {
    event.preventDefault();

    const trimmed = content.trim();
    if (!trimmed || saving) return;
    const expected = scope.current;

    setSaving(true);
    setError("");

    try {
      const response = await fetch(
        `${API_URL}/manuscripts/${manuscriptId}/general-comments`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ content: trimmed }),
        }
      );

      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(
          result.detail || "Unable to save general comment."
        );
      }

      const created = await response.json();
      if (scope.current === expected) {
        setComments((previous) => [...previous, created]); setContent("");
        await loadComments();
      }
    } catch (err) {
      if (scope.current === expected) setError(err.message);
    } finally {
      if (scope.current === expected) setSaving(false);
    }
  };

  return (
    <section className="general-comments-panel" ref={sectionRef}>
      {owner !== scope.current ? <p>Loading comments...</p> : <>
      <div className="general-comments-header">
        <div>
          <h4>General Comments</h4>
          <p>Internal discussion visible to authorized staff only.</p>
        </div>
        <span className="general-comments-badge">Staff Only</span>
      </div>

      {loading ? (
        <p>Loading comments...</p>
      ) : (
        <div className="general-comments-list">
          {comments.length === 0 ? (
            <p className="general-comments-empty">
              No general comments yet.
            </p>
          ) : (
            comments.map((comment) => (
              <article
                className="general-comment"
                key={comment.comment_id}
              >
                <div className="general-comment-meta">
                  <strong>{comment.author_name}</strong>
                  <time>
                    {new Date(comment.created_at).toLocaleString()}
                  </time>
                </div>
                <p>{comment.content}</p>
              </article>
            ))
          )}
        </div>
      )}

      <form
        className="general-comments-form"
        onSubmit={submitComment}
      >
        <label htmlFor={`general-comment-${manuscriptId}`}>
          Add a general comment
        </label>
        <textarea
          id={`general-comment-${manuscriptId}`}
          value={content}
          onChange={(event) => setContent(event.target.value)}
          maxLength={10000}
          rows={3}
          placeholder="Write an internal staff comment..."
          required
        />
        <div className="general-comments-footer">
          <span>{content.length}/10000</span>
          <button type="submit" disabled={saving || !content.trim()}>
            {saving ? "Saving..." : "Add Comment"}
          </button>
        </div>
      </form>

      {error && (
        <p className="general-comments-error" role="alert">
          {error}
        </p>
      )}
      </>}
    </section>
  );
}
