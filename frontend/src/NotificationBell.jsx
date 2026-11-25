import {notificationTitle} from './notificationTitle';
import {recordedMessage} from './recordedDisplay';

import { useCallback, useEffect, useId, useRef, useState } from "react";
import "./NotificationBell.css";

import { API_URL } from "./api";

function notificationDate(value) {
  if (typeof value !== 'string' || !value) return 'Date unavailable';
  const timestamp = /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`;
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString();
}

function NotificationBell({ token, onNavigate, onUnreadSummary, align = "end", onViewAll, onAuthorSnapshot }) {
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [summaryLoaded, setSummaryLoaded] = useState(false);
  const [loadedToken, setLoadedToken] = useState(token);
  const tokenRef = useRef(token);
  const tokenEpoch = useRef(0);
  const requestVersion = useRef(0);
  const badgeId = useId();
  const panelId = useId();
  const bellRef = useRef(null);
  const containerRef = useRef(null);
  if (tokenRef.current !== token) {
    tokenRef.current = token;
    tokenEpoch.current += 1;
    requestVersion.current += 1;
  }
  const currentUser = loadedToken === token;

  const apiRequest = useCallback(
    async (endpoint, options = {}) => {
      const response = await fetch(`${API_URL}${endpoint}`, {
        ...options,
        headers: {
          Authorization: `Bearer ${token}`,
          ...options.headers,
        },
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Request failed");
      }

      return data;
    },
    [token]
  );

  const loadNotifications = useCallback(async () => {
    if (!token || tokenRef.current !== token) return;
    const version = ++requestVersion.current;
    setSummaryLoaded(false);

    try {
      const [items, count] = await Promise.all([
        apiRequest("/notifications/my"),
        apiRequest("/notifications/unread-count"),
      ]);

      if (version !== requestVersion.current || tokenRef.current !== token) return;
      if (!Array.isArray(items)) throw new Error('Invalid notification response');
      if (!Number.isSafeInteger(count.unread_count) || count.unread_count < 0) throw new Error('Invalid notification count');
      setNotifications(items);
      setUnreadCount(count.unread_count);
      setSummaryLoaded(true);
      setError("");
    } catch (err) {
      if (version === requestVersion.current && tokenRef.current === token) setError(err.message || "Failed to load notifications");
    }
  }, [apiRequest, token]);


  useEffect(() => {
    setNotifications([]);
    setUnreadCount(0);
    setError("");
    setSummaryLoaded(false);
    setIsOpen(false);
    setLoading(false);
    setLoadedToken(token);
    loadNotifications();
    const onFocus = () => { if (document.visibilityState === 'visible') loadNotifications(); };
    window.addEventListener('focus', onFocus);
    return () => { requestVersion.current += 1; tokenEpoch.current += 1; window.removeEventListener('focus', onFocus); };
  }, [loadNotifications, token]);

  useEffect(() => {
    if (!onUnreadSummary) return;
    onUnreadSummary({token, state: !currentUser ? 'loading' : error ? 'error' : summaryLoaded ? 'ready' : 'loading', count: currentUser && !error && summaryLoaded ? unreadCount : null, recent: currentUser && !error && summaryLoaded ? notifications.slice(0, 3) : []});
  }, [onUnreadSummary, token, currentUser, error, summaryLoaded, unreadCount, notifications]);


  useEffect(() => {
    if (!isOpen || !currentUser) return undefined;
    const onKeyDown = event => {
      if (event.key === "Escape") {
        event.preventDefault();
        setIsOpen(false);
        bellRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isOpen, currentUser]);

  useEffect(() => {
    if (!isOpen || !onViewAll) return undefined;
    const close = event => { if (!containerRef.current?.contains(event.target)) setIsOpen(false); };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [isOpen, onViewAll]);

  const handleToggle = async () => {
    if (isOpen) { setIsOpen(false); return; }
    const epoch = tokenEpoch.current;
    setIsOpen(true);
    setLoading(true);
    await loadNotifications();
    if (tokenRef.current === token && tokenEpoch.current === epoch) setLoading(false);
  };

  const handleMarkAsRead = useCallback(async (notificationId) => {
    const epoch = tokenEpoch.current;
    try {
      await apiRequest(
        `/notifications/${notificationId}/read`,
        { method: "PATCH" }
      );

      if (tokenEpoch.current === epoch) { await loadNotifications(); return true; }
      return false;
    } catch (err) {
      if (tokenRef.current === token && tokenEpoch.current === epoch) setError(err.message || "Failed to update notification");
      return false;
    }
  }, [apiRequest, loadNotifications, token]);

  useEffect(() => {
    onAuthorSnapshot?.({token, items: currentUser && summaryLoaded && !error ? notifications : [],
      state: !currentUser || (!summaryLoaded && !error) ? 'loading' : error ? 'error' : 'ready',
      error, markRead: handleMarkAsRead, refresh: loadNotifications});
  }, [onAuthorSnapshot, token, currentUser, summaryLoaded, error, notifications, handleMarkAsRead, loadNotifications]);

  const handleNavigate = (notification) => {
    if (!notification.manuscript_id || !onNavigate) {
      return;
    }

    setIsOpen(false);
    onNavigate(notification);
  };

  return (
    <div ref={containerRef} className={`notification-container${align === "start" ? " notification-container-start" : ""}`}>
      <button
        type="button"
        className="notification-bell"
        ref={bellRef}
        onClick={handleToggle}
        aria-label="Notifications"
        aria-expanded={currentUser && isOpen}
        aria-controls={panelId}
        aria-describedby={currentUser && summaryLoaded && !error ? badgeId : undefined}
      >
        <svg className="notification-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
          <path d="M10 20a2 2 0 0 0 4 0" />
        </svg>

        {currentUser && summaryLoaded && !error && unreadCount > 0 && (
          <span className="notification-badge" id={badgeId} aria-live="polite" aria-label={`${unreadCount} unread notifications`}>
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
        {currentUser && summaryLoaded && !error && unreadCount === 0 && (
          <span className="notification-visually-hidden" id={badgeId} aria-live="polite">No unread notifications</span>
        )}
      </button>

      {currentUser && isOpen && (
        <div className="notification-panel" id={panelId} aria-label="Notifications">
          <div className="notification-header">
            <strong>Notifications</strong>

          </div>

          {loading && <p role="status">Loading notifications...</p>}

          {error && (
            <p className="notification-error" role="alert">{error}</p>
          )}

          {!loading && !error && summaryLoaded && notifications.length === 0 && (
            <p className="notification-empty">
              No notifications yet.
            </p>
          )}

          {!loading && !error &&
            (onViewAll ? notifications.slice(0, 5) : notifications).map((notification) => (
              <div
                key={notification.notification_id}
                className={
                  notification.is_read
                    ? "notification-item"
                    : "notification-item unread"
                }
              >

                {onViewAll && <strong className="notification-kind">{notificationTitle(notification.notification_type)}</strong>}

                <button
                  type="button"
                  className="notification-link"
                  onClick={() => handleNavigate(notification)}
                  disabled={!notification.manuscript_id || !onNavigate}
                >
                  {recordedMessage(notification.message)}
                </button>

                <small>{notificationDate(notification.created_at)}</small>

                {!notification.is_read && (
                  <button
                    type="button"
                    onClick={() =>
                      handleMarkAsRead(
                        notification.notification_id
                      )
                    }
                  >
                    Mark as read
                  </button>
                )}
              </div>
            ))}
          {onViewAll && <button type="button" className="notification-view-all" onClick={() => { setIsOpen(false); onViewAll(); }}>View All notifications</button>}
        </div>
      )}
    </div>
  );
}

export default NotificationBell;
