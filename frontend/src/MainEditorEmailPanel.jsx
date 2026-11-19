import { useEffect, useState } from "react";
import { API_URL } from "./api";

// In-app notifications are not evidence that email was queued or delivered.
export default function MainEditorEmailPanel({ token, manuscriptId }) {
  const [state, setState] = useState({ loading: true, error: "", items: [] });
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setState({ loading: true, error: "", items: [] });
    fetch(`${API_URL}/notifications/my`, {
      headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error("Invitation notifications could not be loaded.");
      const data = await response.json();
      if (!Array.isArray(data)) throw new Error("Invitation notifications could not be loaded.");
      if (current) setState({ loading: false, error: "", items: data.filter(item =>
        String(item.manuscript_id) === String(manuscriptId) && item.notification_type === "review_invitation_response"
      ) });
    }).catch(error => {
      if (current && error.name !== "AbortError") setState({ loading: false, error: error.message, items: [] });
    });
    return () => { current = false; controller.abort(); };
  }, [token, manuscriptId]);
  return <section aria-label="Reviewer invitation notifications">
    <h4>Reviewer invitation notifications</h4>
    <p>Email delivery status: Unknown. An in-app notification does not confirm email delivery.</p>
    {state.loading && <p role="status">Loading invitation notifications…</p>}
    {state.error && <p role="alert">{state.error}</p>}
    {!state.loading && !state.error && state.items.length === 0 && <p>No invitation response notifications recorded for this manuscript.</p>}
    {state.items.length > 0 && <ul>{state.items.map(item => <li key={item.notification_id}>{item.message}</li>)}</ul>}
  </section>;
}
