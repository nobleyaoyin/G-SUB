import { useState } from "react";

export default function EmailDemoPanel() {
  const [showPreview, setShowPreview] = useState(false);

  return (
    <section aria-label="Email demo">
      <h3>Email Notification Demo</h3>
      <p>This is a simulated preview. No email has been sent.</p>

      <div>
        <strong>Notification:</strong> Reviewer Invitation
      </div>

      <div>
        <strong>Demo Outbox Status:</strong> Not connected
      </div>

      <div>
        <strong>Recipient:</strong> reviewer@example.com (synthetic)
      </div>

      <button
        type="button"
        onClick={() => setShowPreview(value => !value)}
      >
        {showPreview ? "Hide Email Preview" : "Preview Email"}
      </button>

      {showPreview && (
        <div>
          <h4>Email Preview</h4>
          <p><strong>Subject:</strong> G-Sub — Invitation to Review a Manuscript</p>
          <pre style={{ whiteSpace: "pre-wrap" }}>
{`Dear Reviewer,

A manuscript review invitation is available in G-Sub. Please sign in to G-Sub to review the invitation and choose whether to accept or decline.

Thank you for considering this request.

G-Sub Editorial Team`}
          </pre>
        </div>
      )}
    </section>
  );
}
