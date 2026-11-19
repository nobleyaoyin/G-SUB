import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL } from "./api";
import "./NotesPanel.css";

export default function NotesPanel({ manuscriptId, token, onDirtyChange }) {
  const [notes, setNotes] = useState([]);
  const [content, setContent] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(false);
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

  const endpoint = `${API_URL}/manuscripts/${manuscriptId}/notes`;

  const request = useCallback(async (url, options = {}) => {
    const response = await fetch(url, {
      ...options,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });

    const data = response.status === 204 ? null :
      await response.json().catch(() => null);

    if (!response.ok) {
      throw new Error(data?.detail || "Request failed.");
    }

    return data;
  }, [token]);

  const loadNotes = useCallback(async () => {
    const expected = scope.current, version = ++sequence.current;
    const current = () => scope.current === expected && sequence.current === version;
    setLoading(true);
    setError("");

    try {
      const data = await request(endpoint);
      if (current()) setNotes(data);
    } catch (err) {
      if (current()) setError(err.message);
    } finally {
      if (current()) setLoading(false);
    }
  }, [endpoint, request]);

  useEffect(() => {
    setOwner(scope.current);
    setNotes([]);
    setContent("");
    setEditingId(null);
    setError(""); setSaving(false);
    loadNotes();
    return () => { sequence.current++; };
  }, [loadNotes]);

  const handleSubmit = async (event) => {
    event.preventDefault();

    if (!content.trim() || saving) return;
    const expected = scope.current;

    setSaving(true);
    setError("");

    try {
      if (editingId !== null) {
        await request(`${endpoint}/${editingId}`, {
          method: "PUT",
          body: JSON.stringify({ content: content.trim() }),
        });
      } else {
        await request(endpoint, {
          method: "POST",
          body: JSON.stringify({ content: content.trim() }),
        });
      }

      if (scope.current !== expected) return;
      setContent("");
      setEditingId(null);
      await loadNotes();
    } catch (err) {
      if (scope.current === expected) setError(err.message);
    } finally {
      if (scope.current === expected) setSaving(false);
    }
  };

  const handleEdit = (note) => {
    setEditingId(note.note_id);
    setContent(note.content);
    setError("");
  };

  const handleDelete = async (noteId) => {
    if (!window.confirm("Delete this personal note?")) return;

    const expected = scope.current;
    setError("");

    try {
      await request(`${endpoint}/${noteId}`, {
        method: "DELETE",
      });
      if (scope.current === expected) setNotes((previous) =>
        previous.filter((note) => note.note_id !== noteId)
      );
    } catch (err) {
      if (scope.current === expected) setError(err.message);
    }
  };

  const cancelEdit = () => {
    setEditingId(null);
    setContent("");
    setError("");
  };

  return (
    <section className="personal-notes" ref={sectionRef}>
      {owner !== scope.current ? <p>Loading notes...</p> : <>
      <div className="personal-notes-header">
        <div>
          <h3>My Personal Notes</h3>
          <p>Private notes visible only to you.</p>
        </div>
        <span className="personal-notes-count">
          {notes.length} {notes.length === 1 ? "note" : "notes"}
        </span>
      </div>

      <form className="personal-notes-form" onSubmit={handleSubmit}>
        <label htmlFor={`personal-note-${manuscriptId}`}>
          {editingId !== null ? "Edit note" : "New note"}
        </label>

        <textarea
          id={`personal-note-${manuscriptId}`}
          value={content}
          onChange={(event) => setContent(event.target.value)}
          placeholder="Write down your private thoughts or reminders..."
          maxLength={10000}
          rows={4}
          disabled={saving}
        />

        <div className="personal-notes-form-footer">
          <span>{content.length}/10000</span>
          <div>
            {editingId !== null && (
              <button
                type="button"
                className="notes-cancel-button"
                onClick={cancelEdit}
                disabled={saving}
              >
                Cancel
              </button>
            )}
            <button
              type="submit"
              disabled={saving || !content.trim()}
            >
              {saving
                ? "Saving..."
                : editingId !== null
                  ? "Save Changes"
                  : "Add Note"}
            </button>
          </div>
        </div>
      </form>

      {error && (
        <p className="personal-notes-error" role="alert">
          {error}
        </p>
      )}

      <div className="personal-notes-list">
        {loading ? (
          <p>Loading notes...</p>
        ) : notes.length === 0 ? (
          <p className="personal-notes-empty">
            No personal notes yet.
          </p>
        ) : (
          notes.map((note) => (
            <article className="personal-note-card" key={note.note_id}>
              <p className="personal-note-content">{note.content}</p>

              <div className="personal-note-footer">
                <span>
                  Updated: {new Date(note.updated_at).toLocaleString()}
                </span>

                <div>
                  <button
                    type="button"
                    onClick={() => handleEdit(note)}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="notes-delete-button"
                    onClick={() => handleDelete(note.note_id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            </article>
          ))
        )}
      </div>
      </>}
    </section>
  );
}
