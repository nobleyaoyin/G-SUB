import { PRODUCT_DISPLAY_NAME, PRODUCT_SYSTEM_NAME } from "./branding";
import { roleLabels, roleResponsibilities } from "./roleLabels";
import "./SharedSidebar.css";

const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: "▦" },
  { id: "manuscripts", label: "Manuscripts", icon: "▤" },
  { id: "notifications", label: "Notifications", icon: "♧" },
];

function SharedSidebar({
  user,
  activeSection = "dashboard",
  onNavigate,
  onLogout,
  googleLink,
}) {
  const role = user?.role;
  const roleName = roleLabels[role] || role || "User";

  return (
    <aside className="shared-sidebar" aria-label="Main navigation">
      <div className="shared-sidebar-brand">
        <span className="shared-sidebar-logo" aria-hidden="true">G</span>
        <div>
          <strong>{PRODUCT_DISPLAY_NAME}</strong>
          <small>{PRODUCT_SYSTEM_NAME}</small>
        </div>
      </div>

      <div className="shared-sidebar-user">
        <span className="shared-sidebar-user-name">
          {user?.name || "User"}
        </span>
        <span className="shared-sidebar-user-role">{roleName}</span>
        {roleResponsibilities[role] && <span className="shared-sidebar-user-context">{roleResponsibilities[role]}</span>}
      </div>

      <nav aria-label="Dashboard sections">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={
              "shared-sidebar-link" +
              (activeSection === item.id ? " is-active" : "")
            }
            aria-current={activeSection === item.id ? "page" : undefined}
            disabled={!onNavigate}
            onClick={() => onNavigate?.(item.id)}
          >
            <span aria-hidden="true">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="shared-sidebar-footer">
        {googleLink}
        <button
          type="button"
          className="shared-sidebar-logout"
          onClick={onLogout}
        >
          <span aria-hidden="true">↪</span>
          <span>Logout</span>
        </button>
      </div>
    </aside>
  );
}

export default SharedSidebar;
