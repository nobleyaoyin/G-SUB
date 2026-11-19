
import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";

import AuthorDashboard from "./AuthorDashboard";
import ReviewerDashboard from "./ReviewerDashboard";
import EditorDashboard from "./EditorDashboard";
import EICDashboard from "./EICDashboard";
import FormattingPanel from "./FormattingPanel";
import NotificationBell from "./NotificationBell";
import { PRODUCT_DISPLAY_NAME, PRODUCT_SYSTEM_NAME } from "./branding";
import SharedSidebar from "./SharedSidebar";
import RoleSelection from "./RoleSelection";
import { roleLabels } from "./roleLabels";

import { API_URL } from "./api";
import VerifyEmail from "./VerifyEmail";
import CaptchaWidget from "./CaptchaWidget";
import GoogleLinkPanel from "./GoogleLinkPanel";
import "./WorkspaceVisual.css";

// StrictMode may run effects twice: one receipt must only be exchanged once.
let googleCallbackPromise;
function googleCallback() {
  if (googleCallbackPromise) return googleCallbackPromise;
  const expectedRole = sessionStorage.getItem('google_selected_role');
  sessionStorage.removeItem('google_selected_role');
  window.history.replaceState({}, '', '/');
  googleCallbackPromise = (async () => {
    const response = await fetch(`${API_URL}/users/google/exchange`, {method:'POST'});
    if (!response.ok) throw new Error('Google sign-in expired or could not be completed.');
    const result = await response.json();
    const me = await fetch(`${API_URL}/users/me`, {headers:{Authorization:`Bearer ${result.access_token}`}});
    if (!me.ok) throw new Error('Google account is unavailable.');
    const account = await me.json();
    if (!expectedRole || !matchesSelectedRole(account.role, expectedRole)) throw new Error('The account does not match the selected sign-in role.');
    return {account, token: result.access_token};
  })();
  return googleCallbackPromise;
}

function matchesSelectedRole(accountRole, selectedRole) {
  return accountRole === selectedRole ||
    (selectedRole === "editor" && accountRole === "formatter");
}

function App() {
  const [formatterTarget, setFormatterTarget] = useState(null);
  const [isLogin, setIsLogin] = useState(true);
  const [selectedRole, setSelectedRole] = useState(null);
  const [captcha, setCaptcha] = useState(null);
  const [captchaError, setCaptchaError] = useState('');
  const [captchaToken, setCaptchaToken] = useState(null);
  const [captchaEpoch, setCaptchaEpoch] = useState(0);
  const [googleAvailable, setGoogleAvailable] = useState(false);

  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
  });

  const [user, setUser] = useState(null);
  useEffect(() => {
    if (!selectedRole && !user) return;
    const controller = new AbortController();
    fetch(`${API_URL}/users/auth-options`, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error('Authentication options unavailable'); return response.json(); })
      .then(value => { if (!controller.signal.aborted) { setCaptcha(value.captcha); setGoogleAvailable(value.google === true); setCaptchaError(''); } })
      .catch(() => { if (!controller.signal.aborted) { setCaptcha(null); setCaptchaError('Authentication options are unavailable. Please try again later.'); } });
    return () => controller.abort();
  }, [selectedRole, user]);
  const [activeSection, setActiveSection] = useState("dashboard");
  const contentRef = useRef(null);
  const manuscriptReturnRef = useRef(null);
  const registerManuscriptReturn = useCallback(handler => {
    manuscriptReturnRef.current = handler;
    return () => { if (manuscriptReturnRef.current === handler) manuscriptReturnRef.current = null; };
  }, []);
  const profileDirtyRef = useRef(false);
  const handleProfileDirtyChange = useCallback(value => { profileDirtyRef.current = value; }, []);

  const [token, setToken] = useState(
    () => sessionStorage.getItem("access_token")
  );

  const [loading, setLoading] = useState(false);
  const [checkingAuth, setCheckingAuth] = useState(Boolean(token));
  const verifiedToken = useRef(null);

  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [needsEmailVerification, setNeedsEmailVerification] = useState(false);

  useEffect(() => {
    if (window.location.pathname !== '/google-callback' && !googleCallbackPromise) return;
    let cancelled = false;
    googleCallback().then(result => {
      if (!cancelled) { verifiedToken.current = result.token; sessionStorage.setItem('access_token',result.token); setToken(result.token); setUser(result.account); }
    }).catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, []);

  // Send requests to FastAPI
  const apiRequest = async (endpoint, options = {}) => {
    const response = await fetch(`${API_URL}${endpoint}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    const contentType =
      response.headers.get("content-type") || "";

    let data;

    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      const text = await response.text();
      data = {
        detail: text || "Request failed",
      };
    }

    if (!response.ok) {
      const detail = data.detail;
      const tunnelSessionError =
        response.status === 401 &&
        !contentType.includes("application/json") &&
        typeof detail === "string" &&
        detail.trim() === "Unauthorized";

      const requestError = new Error(
        tunnelSessionError
          ? "Your protected tunnel session may have expired. Refresh this page and sign in through Cloudflare again, then retry."
          : typeof detail === "string"
          ? detail
          : JSON.stringify(detail || "Request failed")
      );

      requestError.status = response.status;
      throw requestError;
    }

    return data;
  };

  // Get the current user's information
  const fetchCurrentUser = async (accessToken) => {
    return await apiRequest("/users/me", {
      method: "GET",
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    });
  };

  // Restore login after refreshing the page
  useEffect(() => {
    if (!token) {
      setCheckingAuth(false);
      return;
    }

    let cancelled = false;

    setCheckingAuth(true);

    fetchCurrentUser(token)
      .then((currentUser) => {
        if (!cancelled) {
          verifiedToken.current = token;
          setUser(currentUser);
          setError("");
        }
      })
      .catch((err) => {
        if (cancelled) return;

        setUser(null);

        if (err.status === 401 || err.status === 403) {
          sessionStorage.removeItem("access_token");
          setToken(null);
          setError("Your session has expired. Please sign in again.");
        } else {
          setError(
            "Unable to connect to the server. Please refresh the page and try again."
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCheckingAuth(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  // Handle input changes
  const handleChange = (e) => {
    const { name, value } = e.target;

    setForm((previousForm) => ({
      ...previousForm,
      [name]: value,
    }));
  };

  // Handle login and registration
  const startGoogle = async () => {
    setError(''); setLoading(true);
    try {
      const data = await apiRequest('/users/google/start', { method:'POST', body:JSON.stringify({captcha_token:captchaToken}) });
      sessionStorage.setItem('google_selected_role',selectedRole);
      window.location.assign(data.authorization_url);
    } catch (e) { setError(e.message || 'Google sign-in is unavailable.'); }
    finally { setCaptchaToken(null); setCaptchaEpoch(value => value + 1); setLoading(false); }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    setLoading(true);
    setError("");
    setMessage("");
    setNeedsEmailVerification(false);

    try {
      if (isLogin) {
        // Step 1: Login
        const loginData = await apiRequest("/users/login", {
          method: "POST",
          body: JSON.stringify({
            email: form.email,
            password: form.password,
            captcha_token: captchaToken,
          }),
        });

        // Step 2: Get user information
        const currentUser = await fetchCurrentUser(
          loginData.access_token
        );

        if (!matchesSelectedRole(currentUser.role, selectedRole)) {
          setForm(previous => ({ ...previous, password: "" }));
          setError("The account does not match the selected sign-in role. Choose the correct role and try again.");
          return;
        }

        // Step 3: Save login state
        sessionStorage.setItem(
          "access_token",
          loginData.access_token
        );

        verifiedToken.current = loginData.access_token;
        setUser(currentUser);
        setToken(loginData.access_token);

        setForm({
          name: "",
          email: "",
          password: "",
        });
      } else {
        // Register a new author account
        await apiRequest("/users/register", {
          method: "POST",
          body: JSON.stringify({
            name: form.name,
            email: form.email,
            password: form.password,
            captcha_token: captchaToken,
          }),
        });

        setMessage(
          "Registration successful! If a verification email was sent, please verify your email address before signing in."
        );

        setIsLogin(true);
        setSelectedRole("author");

        setForm({
          name: "",
          email: form.email,
          password: "",
        });
      }
    } catch (err) {
      const errorMessage = err.message || "Something went wrong.";
      setError(errorMessage);

      if (
        isLogin &&
        err.status === 403 &&
        errorMessage.includes("verify your email address")
      ) {
        setNeedsEmailVerification(true);
      }
    } finally {
      setCaptchaToken(null);
      setCaptchaEpoch(value => value + 1);
      setLoading(false);
    }
  };

  // Resend email verification without requiring a login token.
  const handleResendVerification = async () => {
    if (!form.email || !form.password) {
      setError("Enter your email and password first.");
      return;
    }

    setLoading(true);
    setError("");
    setMessage("");

    try {
      const result = await apiRequest("/users/resend-verification", {
        method: "POST",
        body: JSON.stringify({
          email: form.email,
          password: form.password,
        }),
      });

      if (result.sent) {
        setMessage("Verification email sent. Please check your inbox.");
      } else {
        setMessage(result.message || "No verification email was sent.");
      }
    } catch (err) {
      setError(err.message || "Unable to resend verification email.");
    } finally {
      setLoading(false);
    }
  };

  // Logout
  const handleLogout = () => {
    if (profileDirtyRef.current && !window.confirm("Discard unsaved profile changes and log out?")) return;
    profileDirtyRef.current = false;
    setActiveSection("dashboard");
    sessionStorage.removeItem("access_token");
    verifiedToken.current = null;

    setToken(null);
    setUser(null);
    setCheckingAuth(false);

    setError("");
    setMessage("");

    setForm({
      name: "",
      email: "",
      password: "",
    });

    setIsLogin(true);
    setSelectedRole(null);
  };

  // Show loading screen while restoring login
  if (checkingAuth && !user) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="brand-icon">G</div>

          <h1>{PRODUCT_DISPLAY_NAME} {PRODUCT_SYSTEM_NAME}</h1>

          <p className="subtitle">
            Checking your session...
          </p>
        </div>
      </div>
    );
  }

  // Shared layout for authenticated dashboard roles.
  if (user && ["author", "editor", "reviewer", "eic", "formatter"].includes(user.role)) {
    let dashboard;

    if (user.role === "author") {
      dashboard = <AuthorDashboard user={user} token={token} registerManuscriptReturn={registerManuscriptReturn} />;
    } else if (user.role === "editor") {
      dashboard = <EditorDashboard user={user} token={token} registerManuscriptReturn={registerManuscriptReturn} />;
    } else if (user.role === "reviewer") {
      dashboard = <ReviewerDashboard user={user} token={token} onProfileDirtyChange={handleProfileDirtyChange} registerManuscriptReturn={registerManuscriptReturn} />;
    } else if (user.role === "eic") {
      dashboard = <EICDashboard user={user} token={token} registerManuscriptReturn={registerManuscriptReturn} />;
    } else {
      dashboard = (
        <main>
          <h1>General / Copy Editor Dashboard</h1>
          <p>Welcome, {user.name}</p>
          <NotificationBell token={token} onNavigate={item => setFormatterTarget({ manuscriptId: item.manuscript_id })} />
          <FormattingPanel role="formatter" token={token} navigationTarget={formatterTarget} registerManuscriptReturn={registerManuscriptReturn} />
        </main>
      );
    }

    const verifying = checkingAuth || verifiedToken.current !== token;
    return (
      <>
      {verifying && <p role="status">Checking your session...</p>}
      <div className="app-shell" hidden={verifying} style={verifying ? { display: 'none' } : undefined}>
        <SharedSidebar user={user} onLogout={handleLogout} activeSection={activeSection} googleLink={googleAvailable ? <GoogleLinkPanel token={token} role={user.role} /> : null} onNavigate={(section) => {
          const content = contentRef.current;
          if (section === "notifications") {
            const bell = content?.querySelector(".notification-bell");
            if (bell) {
              bell.scrollIntoView?.({ block: "center" });
              if (bell.getAttribute("aria-expanded") !== "true") bell.click();
              bell.focus();
              setActiveSection(section);
            }
          } else if (section === "manuscripts") {
            if (manuscriptReturnRef.current?.() === false) return;
            setActiveSection(section);
            requestAnimationFrame(() => {
              const target = contentRef.current?.querySelector('[data-sidebar-target="manuscripts"]');
              if (target) { target.setAttribute("tabindex", "-1"); target.focus(); target.scrollIntoView?.({ block: "start" }); }
            });
          } else if (content) {
            content.scrollIntoView?.({ block: "start" }); setActiveSection(section);
          }
        }} />
        <div className="app-shell-content" ref={contentRef}>{dashboard}</div>
      </div>
      </>
    );
  }

  // Fallback for an unknown user role
  if (user) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="brand-icon">G</div>

          <h1>Welcome, {user.name}!</h1>

          <p className="subtitle">
            You have successfully signed in.
          </p>

          <div className="user-info">
            <p>
              <strong>User ID:</strong> {user.user_id}
            </p>

            <p>
              <strong>Name:</strong> {user.name}
            </p>

            <p>
              <strong>Email:</strong> {user.email}
            </p>

            <p>
              <strong>Role:</strong> {user.role}
            </p>
          </div>

          <button
            className="submit-button"
            onClick={handleLogout}
          >
            Logout
          </button>

          <p className="footer-text">
            No dashboard is available for this role.
          </p>
        </div>
      </div>
    );
  }

  // Login / Register page
  if (!selectedRole) {
    return <RoleSelection onSelect={(role) => { setSelectedRole(role); setError(""); setMessage(""); }} error={error} />;
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">{PRODUCT_DISPLAY_NAME}<span>.</span></div>

        <h1>{isLogin ? "Sign in" : "Create author account"}</h1>

        <p className="subtitle">
          {isLogin ? `Selected role: ${roleLabels[selectedRole]}` : "Registration creates an Author / Submitter account."}
        </p>
        <button type="button" className="change-role" onClick={() => { setSelectedRole(null); setIsLogin(true); setError(""); setMessage(""); setForm({ name: "", email: "", password: "" }); }}>← Choose a different role</button>

        <div className="auth-tabs">
          <button
            type="button"
            className={isLogin ? "active" : ""}
            onClick={() => {
              setIsLogin(true);
              setError("");
              setMessage("");
            }}
          >
            Login
          </button>

          <button
            type="button"
            className={!isLogin ? "active" : ""}
            onClick={() => {
              setIsLogin(false);
              setError("");
              setMessage("");
            }}
          >
            Register
          </button>
        </div>

        {error && (
          <div className="error-message" role="alert">
            {error}
          </div>
        )}

        {message && (
          <div className="success-message" role="status">
            {message}
          </div>
        )}
        {captchaError && <p role="status">{captchaError}</p>}

        {isLogin && needsEmailVerification && (
            <button
              type="button"
              className="change-role"
              onClick={handleResendVerification}
              disabled={loading}
            >
              {loading ? "Sending..." : "Resend Verification Email"}
            </button>
          )}

        <form onSubmit={handleSubmit}>
          {!isLogin && (
            <div className="form-group">
              <label htmlFor="name">
                Full Name
              </label>

              <input
                id="name"
                type="text"
                name="name"
                placeholder="Enter your full name"
                value={form.name}
                onChange={handleChange}
                required
              />
            </div>
          )}

          <div className="form-group">
            <label htmlFor="email">
              Email Address
            </label>

            <input
              id="email"
              type="email"
              name="email"
              placeholder="Enter your email"
              value={form.email}
              onChange={handleChange}
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">
              Password
            </label>

            <input
              id="password"
              type="password"
              name="password"
              placeholder="Enter your password"
              value={form.password}
              onChange={handleChange}
              minLength={isLogin ? 1 : 8}
              required
            />
          </div>

          {captcha?.provider === 'hcaptcha' && <CaptchaWidget key={captchaEpoch} siteKey={captcha.site_key} onToken={setCaptchaToken} />}

          <button
            className="submit-button"
            type="submit"
            disabled={loading}
          >
            {loading
              ? "Please wait..."
              : isLogin
                ? "Sign In"
                : "Create Account"}
          </button>
        </form>
        {isLogin && googleAvailable && <button type="button" className="submit-button" onClick={startGoogle} disabled={loading}>Continue with Google</button>}
        {isLogin && !googleAvailable && <p className="footer-text">Google sign-in is not configured.</p>}

        <p className="footer-text">
          {PRODUCT_SYSTEM_NAME} · Peer Review
        </p>
      </div>
    </div>
  );
}

function AppRouter() {
  if (window.location.pathname === "/verify-email") {
    return <VerifyEmail />;
  }

  return <App />;
}

export default AppRouter;
