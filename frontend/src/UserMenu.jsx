import { useEffect, useRef, useState } from "react";
import { roleLabels } from "./roleLabels";
import "./UserMenu.css";

export default function UserMenu({ user, onLogout, onProfile }) {
  const [open, setOpen] = useState(false);
  const container = useRef(null);
  const trigger = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const outside = event => { if (!container.current?.contains(event.target)) setOpen(false); };
    const keydown = event => {
      if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", keydown);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", keydown); };
  }, [open]);
  const role = user?.role === "formatter" ? "Formatter" : (roleLabels[user?.role] || user?.role || "User");
  return <div className="user-menu" ref={container}>
    <button ref={trigger} type="button" className="user-menu-trigger" aria-label="User menu" aria-expanded={open} aria-controls="account-menu" onClick={() => setOpen(value => !value)}>
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c.5-4 3-6 7-6s6.5 2 7 6"/></svg>
    </button>
    {open && <section id="account-menu" className="user-menu-panel" aria-label="Account menu">
      <h2>Profile Information</h2>
      <strong>{user?.name || "User"}</strong>
      {user?.email && <span className="user-menu-email">{user.email}</span>}
      <span>{role}</span>
      {onProfile && <button type="button" className="user-menu-profile" onClick={() => { setOpen(false); onProfile(); }}>My Profile</button>}
      <button type="button" className="user-menu-logout" onClick={onLogout}><span aria-hidden="true">↪</span> Logout</button>
    </section>}
  </div>;
}
