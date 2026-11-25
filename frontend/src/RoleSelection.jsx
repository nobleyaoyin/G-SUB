import "./RoleSelection.css";
import { roleLabels } from "./roleLabels";
import { PRODUCT_DISPLAY_NAME, PRODUCT_SYSTEM_NAME } from "./branding";

const roles = [
  { id: "eic", icon: "☆" },
  { id: "editor", icon: "✎" },
  { id: "reviewer", icon: "⌕" },
  { id: "author", icon: "▤" },
];

export default function RoleSelection({ onSelect, error }) {
  return (
    <main className="role-page">
      <div className="role-shell">
        <header className="role-heading">
          <h1>{PRODUCT_DISPLAY_NAME}<span>.</span></h1>
          <p>{PRODUCT_SYSTEM_NAME}</p>
        </header>
        {error && <p className="role-error" role="alert">{error}</p>}
        <div className="role-grid" role="group" aria-label="Choose a sign-in role">
          {roles.map(role => (
            <button key={role.id} type="button" className={`role-card role-${role.id}`} onClick={() => onSelect(role.id)} aria-labelledby={`role-${role.id}-name`}>
              <span className="role-icon" aria-hidden="true">{role.icon}</span>
              <span id={`role-${role.id}-name`} className="role-name">{roleLabels[role.id]}</span>
            </button>
          ))}
        </div>
        <p className="role-note">Your account permissions are determined by the system after sign-in. Initial and final editing are assignments. Editor and formatter accounts use General / Copy Editor; formatting requires an assignment.</p>
      </div>
    </main>
  );
}
