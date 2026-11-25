import {useEffect, useState} from 'react';
import {API_URL} from './api';
import LifecycleAdministration from './LifecycleAdministration';

// The backend remains the authority for every lifecycle operation.
export default function LifecycleAdministrationAccess({token, currentUserId}) {
  const [access, setAccess] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    setAccess(null);
    fetch(`${API_URL}/lifecycle-admin/eics`, {headers:{Authorization:`Bearer ${token}`}, cache:'no-store', signal:controller.signal})
      .then(async response => response.ok ? response.json() : null)
      .then(users => { if (!controller.signal.aborted && Array.isArray(users)) setAccess({token, users}); })
      .catch(() => {});
    return () => controller.abort();
  }, [token]);
  return access?.token === token ? <LifecycleAdministration token={token} currentUserId={currentUserId} initialUsers={access.users} /> : null;
}
