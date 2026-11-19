import { useState } from 'react';
import { API_URL } from './api';

export default function GoogleLinkPanel({ token, role }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const response = await fetch(`${API_URL}/users/google/link/start`, {method:'POST', headers:{'Content-Type':'application/json', Authorization:`Bearer ${token}`}, body:JSON.stringify({password})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Google linking is unavailable');
      sessionStorage.setItem('google_selected_role',role);
      sessionStorage.removeItem('access_token');
      window.location.assign(result.authorization_url);
    } catch (e) { setError(e.message); }
    finally { setPassword(''); setBusy(false); }
  };
  return <div><button type="button" className="shared-sidebar-link" onClick={() => setOpen(!open)} aria-expanded={open}>Link Google account</button>
    {open && <form onSubmit={submit}><label>Confirm current password<input type="password" autoComplete="current-password" required maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label>
      {error && <p role="alert">{error}</p>}<button type="submit" disabled={busy}>Continue to Google</button></form>}</div>;
}
