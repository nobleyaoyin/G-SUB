import {workflowStatusLabel} from './workflowStatus';
import { useEffect, useState } from "react";
import { API_URL } from "./api";

const display = value => workflowStatusLabel(typeof value === 'string' ? value : null);

export default function AIPrescreeningPanel({ manuscriptId, token, revision = 0 }) {
  const [state, setState] = useState({
    loading: true,
    error: "",
    submissions: [],
  });

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        const response = await fetch(
          `${API_URL}/eic/manuscripts/${manuscriptId}/ai-prescreening`,
          {
            headers: { Authorization: `Bearer ${token}` },
            signal: controller.signal,
          }
        );

        if (!response.ok) {
          throw new Error(`AI report request failed (${response.status})`);
        }

        const data = await response.json();

        if (!controller.signal.aborted) {
          setState({
            loading: false,
            error: "",
            submissions: Array.isArray(data.submissions)
              ? data.submissions
              : [],
          });
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setState({
            loading: false,
            error: error.message,
            submissions: [],
          });
        }
      }
    }

    load();

    return () => controller.abort();
  }, [manuscriptId, token, revision]);

  return (
    <section aria-label="AI Prescreening">
      <h3>AI Prescreening</h3>
      <p>
        Advisory only. AI findings do not automatically approve,
        reject, or request revisions to a manuscript.
      </p>

      {state.loading && <p>Loading AI reports...</p>}

      {state.error && (
        <p role="alert">AI reports unavailable: {state.error}</p>
      )}

      {!state.loading && !state.error && state.submissions.length === 0 && (
        <p>No AI prescreening results are available for this manuscript.</p>
      )}

      {!state.loading && !state.error &&
        state.submissions.map(submission => {
          const analysis = submission.analysis;

          return (
            <article key={submission.snapshot_id}>
              <h4>
                Submission #{submission.submission_sequence}
                {" · "}
                {display(submission.submission_kind)}
              </h4>

              <p>
                <strong>Review round:</strong> {submission.review_round}
                {" · "}
                <strong>Format:</strong> {display(submission.file_format)}
              </p>

              <p>
                <strong>AI status:</strong> {display(submission.status)}
              </p>

              {analysis && (
                <>
                  <p>
                    <strong>Engine:</strong> {typeof analysis.engine === 'string' ? analysis.engine.replaceAll('_', ' ') : 'Unavailable'}
                    {" · "}
                    <strong>Word count:</strong> {analysis.word_count ?? "N/A"}
                  </p>

                  <p>
                    <strong>Detected sections:</strong>{" "}
                    {Array.isArray(analysis.sections_detected)
                      ? analysis.sections_detected.join(", ") || "None"
                      : "Unavailable"}
                  </p>

                  <h5>Advisory Findings</h5>

                  {Array.isArray(analysis.findings) &&
                  analysis.findings.length > 0 ? (
                    <ul>
                      {analysis.findings.map((finding, index) => (
                        <li key={`${finding.code ?? "finding"}-${index}`}>
                          <strong>{display(finding.severity)}:</strong>{" "}
                          {finding.message}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>No advisory findings reported.</p>
                  )}
                </>
              )}

              {submission.status === "completed" && !analysis && (
                <p>Completed report is unavailable.</p>
              )}
            </article>
          );
        })}
    </section>
  );
}
