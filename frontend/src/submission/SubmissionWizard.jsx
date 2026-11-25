import { useCallback, useEffect, useState } from "react";
import { metadataCounts } from "./metadataCounts";
import { ManuscriptVersionHistory } from "../DocumentDistribution";
import { originalDocumentName } from "../documentNames";
import "./SubmissionWizard.css";

const MAX_FILE_SIZE = 10 * 1024 * 1024;
const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".doc", ".txt"];

function SubmissionWizard({
  onCreateDraft,
  onUpdateDraft,
  onUploadFile,
  onSubmitDraft,
  onClose,
  initialManuscript = null,
  onStateChange,
  token,
  onDownloadCurrent,
  downloadBusy = false,
  renderDocumentEditor,
  documentDirty = false,
  onDiscardDocumentEdits,
  getSelectedOnlineDraft,
}) {
  const [step, setStep] = useState(() => {
    if (!initialManuscript) return 1;

    return 2;
  });

  const [manuscriptId, setManuscriptId] = useState(
    initialManuscript?.manuscript_id ?? null
  );

  const [title, setTitle] = useState(
    initialManuscript?.title ?? ""
  );

  const [abstract, setAbstract] = useState(
    initialManuscript?.abstract ?? ""
  );

  const [savedFields, setSavedFields] = useState(() => ({ title: initialManuscript?.title ?? "", abstract: initialManuscript?.abstract ?? "" }));
  const [file, setFile] = useState(null);

  const [hasUploadedFile, setHasUploadedFile] = useState(
    Boolean(initialManuscript?.has_pdf)
  );

  const [uploadedFilename, setUploadedFilename] = useState(
    initialManuscript?.file_type
      ? `Existing manuscript file (${initialManuscript.file_type.toUpperCase()})`
      : ""
  );
  const [currentVersion, setCurrentVersion] = useState(null);
  const [currentFormat, setCurrentFormat] = useState(initialManuscript?.file_type || null);
  const [sessionFilename, setSessionFilename] = useState(null);
  const [sessionVersion, setSessionVersion] = useState(null);
  const [historyChecked, setHistoryChecked] = useState(false);
  const receiveCurrentVersion = useCallback(value => { setCurrentVersion(value); setHistoryChecked(true); }, []);
  const sessionNameIsCurrent = !historyChecked || Boolean(currentVersion && sessionVersion &&
    ((sessionVersion.versionId && currentVersion.version_id === sessionVersion.versionId) ||
     (sessionVersion.filename && currentVersion.filename === sessionVersion.filename)));
  const displayFilename = originalDocumentName(currentVersion) || (sessionNameIsCurrent ? sessionFilename : null);

  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const dirty = step !== 4 && (title !== savedFields.title || abstract !== savedFields.abstract || Boolean(file) || documentDirty);
  const busy = saving || uploading || submitting;
  useEffect(() => { onStateChange?.({ dirty, busy }); }, [onStateChange, dirty, busy]);

  const validateFile = (selectedFile) => {
    if (!selectedFile) {
      throw new Error("Please select a manuscript file.");
    }

    const extension = selectedFile.name
      .slice(selectedFile.name.lastIndexOf("."))
      .toLowerCase();

    if (!ALLOWED_EXTENSIONS.includes(extension)) {
      throw new Error(
        "Only PDF, DOCX, DOC, and TXT files are allowed."
      );
    }

    if (selectedFile.size === 0) {
      throw new Error("The manuscript file is empty.");
    }

    if (selectedFile.size > MAX_FILE_SIZE) {
      throw new Error("The maximum file size is 10 MB.");
    }
  };

  // Step 1: Save manuscript information.
  const handleContinue = async (event) => {
    event.preventDefault();

    if (saving) return;

    if (!title.trim() || !abstract.trim()) {
      setError("Title and Abstract cannot be empty.");
      return;
    }
    if (metadataCounts(title.trim()).characters > 255) {
      setError("Title must not exceed 255 characters.");
      return;
    }

    setSaving(true);
    setError("");
    setMessage("");

    try {
      let manuscript;

      if (manuscriptId === null) {
        manuscript = await onCreateDraft({
          title: title.trim(),
          abstract: abstract.trim(),
        });

        if (!manuscript?.manuscript_id) {
          throw new Error(
            "Draft was created but its ID was not returned."
          );
        }

        setManuscriptId(manuscript.manuscript_id);
      } else {
        manuscript = await onUpdateDraft(manuscriptId, {
          title: title.trim(),
          abstract: abstract.trim(),
        });
      }

      setSavedFields({ title: title.trim(), abstract: abstract.trim() });
      setTitle(title.trim());
      setAbstract(abstract.trim());
      setStep(2);
    } catch (err) {
      setError(
        err.message || "Could not save manuscript information."
      );
    } finally {
      setSaving(false);
    }
  };

  // Step 2: Upload or replace the manuscript file.
  const handleUpload = async (event) => {
    event.preventDefault();

    if (uploading || !file || !manuscriptId) return;
    if (documentDirty) { setError("Save or close the document editor before replacing the file."); return; }

    setUploading(true);
    setError("");
    setMessage("");

    try {
      validateFile(file);

      const result = await onUploadFile(manuscriptId, file);

      if (result === false) {
        throw new Error(
          "The file upload could not be confirmed. Please check your manuscript before continuing."
        );
      }

      setHasUploadedFile(true);
      setUploadedFilename(file.name);
      setSessionFilename(file.name);
      setSessionVersion(result && typeof result === 'object' ? result : null);
      setHistoryChecked(false);
      setCurrentFormat(file.name.split('.').pop().toLowerCase());
      setCurrentVersion(null);
      setFile(null);
      setMessage("Manuscript file uploaded successfully.");

      setStep(3);
    } catch (err) {
      setError(err.message || "Manuscript upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleFileChange = (event) => {
    const selectedFile = event.target.files?.[0] || null;

    setError("");
    setMessage("");

    if (!selectedFile) {
      setFile(null);
      return;
    }

    try {
      validateFile(selectedFile);
      setFile(selectedFile);
    } catch (err) {
      setFile(null);
      setError(err.message);
      event.target.value = "";
    }
  };

  // Continue with an already uploaded manuscript file.
  const handleContinueToReview = () => {
    if (documentDirty) { setError("Save or close the document editor before continuing."); return; }
    if (!hasUploadedFile) {
      setError("Upload a manuscript file before continuing.");
      return;
    }

    setError("");
    setMessage("");
    setStep(3);
  };

  // Step 3: Submit using the existing Dashboard submission handler.
  const handleSubmit = async () => {
    if (submitting || !manuscriptId) return;

    if (!hasUploadedFile) {
      setError("A manuscript file is required before submission.");
      return;
    }

    setSubmitting(true);
    setError("");
    setMessage("");

    try {
      const result = await onSubmitDraft(manuscriptId);

      if (result === false) {
        throw new Error(
          "Submission was not completed. Please try again."
        );
      }

      setStep(4);
    } catch (err) {
      setError(
        err.message || "Failed to submit manuscript."
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleExit = () => {
    if (saving || uploading || submitting) return;
    if (dirty && !window.confirm("Discard unsaved submission changes?")) return;
    onClose();
  };

  const visibleStep = Math.min(step, 3);

  return (
    <section
      className="submission-wizard"
      aria-labelledby="submission-wizard-heading"
    >
      <div className="wizard-header">
        <div>
          <p className="wizard-eyebrow">AUTHOR PORTAL</p>

          <h2 id="submission-wizard-heading">
            {step === 4
              ? "Submission Complete"
              : initialManuscript
                ? "Continue Manuscript Submission"
                : "New Manuscript Submission"}
          </h2>

          <p className="wizard-description">
            {step === 4
              ? "Your manuscript has been submitted successfully."
              : "Complete the submission information and review your manuscript before submitting it."}
          </p>
        </div>

        {step !== 4 && (
          <button
            type="button"
            className="wizard-close"
            onClick={handleExit}
            disabled={saving || uploading || submitting}
            aria-label="Close submission wizard"
          >
            ×
          </button>
        )}
      </div>

      {step !== 4 && (
        <div className="wizard-progress">
          <div className="wizard-progress-heading">
            <span>Submission Process</span>
            <span>Step {visibleStep} of 3</span>
          </div>

          <div
            className="wizard-progress-track"
            role="progressbar"
            aria-valuenow={visibleStep}
            aria-valuemin={1}
            aria-valuemax={3}
            aria-label="Submission progress"
          >
            <div
              className="wizard-progress-fill"
              style={{
                width: `${(visibleStep / 3) * 100}%`,
              }}
            />
          </div>

          <div className="wizard-step-labels">
            <span className={step === 1 ? "active" : "completed"}>
              1. Information
            </span>

            <span
              className={
                step === 2
                  ? "active"
                  : step > 2
                    ? "completed"
                    : ""
              }
            >
              2. Upload
            </span>

            <span className={step === 3 ? "active" : ""}>
              3. Review & Submit
            </span>
          </div>
        </div>
      )}

      {error && (
        <div id="wizard-error" className="wizard-alert error" role="alert">
          {error}
        </div>
      )}

      {message && (
        <div className="wizard-alert success" role="status">
          {message}
        </div>
      )}

      {/* STEP 1: MANUSCRIPT INFORMATION */}
      {step === 1 && (
        <form
          className="wizard-form"
          onSubmit={handleContinue}
        >
          <div className="wizard-section-heading">
            <h3>Manuscript Information</h3>
            <p>Enter the basic information about your manuscript.</p>
          </div>

          <div className="wizard-field">
            <label htmlFor="wizard-title">
              Manuscript Title <span>*</span>
            </label>

            <input
              id="wizard-title"
              type="text"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Enter your manuscript title"
              required
              disabled={saving}
              aria-describedby={`wizard-title-count${error ? ' wizard-error' : ''}`}
              aria-invalid={Boolean(error && (!title.trim() || metadataCounts(title.trim()).characters > 255))}
            />

            <small id="wizard-title-count">{metadataCounts(title).characters}/255 characters</small>
          </div>

          <div className="wizard-field">
            <label htmlFor="wizard-abstract">
              Abstract <span>*</span>
            </label>

            <textarea
              id="wizard-abstract"
              value={abstract}
              onChange={(event) => setAbstract(event.target.value)}
              placeholder="Enter your manuscript abstract"
              rows={9}
              required
              disabled={saving}
              aria-describedby={`wizard-abstract-help wizard-abstract-count wizard-count-method${error ? ' wizard-error' : ''}`}
              aria-invalid={Boolean(error && !abstract.trim())}
            />

            <small id="wizard-abstract-help">
              Provide a clear summary of your research and its main findings.
            </small>
            <small id="wizard-abstract-count" aria-live="polite">{metadataCounts(abstract).words} words · {metadataCounts(abstract).characters} characters (display count)</small>
            <small id="wizard-count-method">Words are separated by whitespace; characters are Unicode code points. These counts are informational, not submission limits.</small>
          </div>
          <p>Keywords are not collected in this submission. Body word count is unavailable until a reliable extraction workflow is approved.</p>

          <div className="wizard-actions">
            <button
              type="button"
              className="wizard-secondary"
              onClick={handleExit}
              disabled={saving}
            >
              Cancel
            </button>

            <button
              type="submit"
              className="wizard-primary"
              disabled={saving}
            >
              {saving ? "Saving..." : "Save & Continue"}
              {!saving && <span aria-hidden="true"> →</span>}
            </button>
          </div>
        </form>
      )}

      {/* STEP 2: MANUSCRIPT FILE */}
      {step === 2 && (
        <form
          className="wizard-form"
          onSubmit={handleUpload}
        >
          <div className="wizard-section-heading">
            <h3>Upload Manuscript</h3>
            <p>
              Upload the main document you want to submit for review.
            </p>
          </div>

          <div className="wizard-manuscript-summary">
            <span className="wizard-summary-label">
              Manuscript
            </span>

            <strong>{title}</strong>
            <span>Draft #{manuscriptId}</span>
          </div>

          {hasUploadedFile && !file && (
            <div className="wizard-uploaded-file" role="status">
              <strong>✓ Existing file available</strong>
              <span>Current filename: {displayFilename || "Original filename unavailable"}</span>
              <span>Format: {currentFormat ? currentFormat.toUpperCase() : "Unavailable"}</span>
              <span>Version: {Number.isInteger(currentVersion?.version_number) && currentVersion.version_number > 0 ? currentVersion.version_number : "Unavailable"}</span>
            </div>
          )}

          {hasUploadedFile && onDownloadCurrent && <button type="button" className="wizard-secondary" disabled={downloadBusy} onClick={() => onDownloadCurrent(manuscriptId)}>{downloadBusy ? "Downloading..." : "Download Current File"}</button>}
          {getSelectedOnlineDraft?.(manuscriptId) && <p role="status">{getSelectedOnlineDraft(manuscriptId)}</p>}
          {hasUploadedFile && renderDocumentEditor && <div className="wizard-document-editor">{renderDocumentEditor(manuscriptId, currentFormat)}</div>}
          {hasUploadedFile && token && manuscriptId && <ManuscriptVersionHistory token={token} manuscriptId={manuscriptId} onCurrentVersion={receiveCurrentVersion} historyOnly authorView />}

          <div className="wizard-upload-area">
            <label htmlFor="wizard-file">
              <span className="wizard-upload-icon" aria-hidden="true">
                ↑
              </span>

              <strong>
                {hasUploadedFile
                  ? "Select a Replacement File"
                  : "Select Manuscript File"}
              </strong>

              <span>
                PDF, DOCX, DOC, or TXT · Maximum 10 MB
              </span>
            </label>

            <input
              id="wizard-file"
              type="file"
              accept=".pdf,.docx,.doc,.txt"
              onChange={handleFileChange}
              disabled={uploading}
            />

            {file && (
              <div className="wizard-selected-file">
                <span>{file.name}</span>
                <span>Format: {file.name.split('.').pop().toUpperCase()} · Size: {file.size.toLocaleString()} bytes</span>

                <button
                  type="button"
                  onClick={() => setFile(null)}
                  disabled={uploading}
                  aria-label="Remove selected file"
                >
                  Remove
                </button>
              </div>
            )}
          </div>

          <div className="wizard-actions">
            <button
              type="button"
              className="wizard-secondary"
              onClick={() => {
                if (documentDirty && !window.confirm("Discard unsaved document edits?")) return;
                if (documentDirty) onDiscardDocumentEdits?.();
                setStep(1);
                setError("");
                setMessage("");
              }}
              disabled={uploading}
            >
              ← Previous
            </button>

            <div className="wizard-action-group">
              <button
                type="button"
                className="wizard-secondary"
                onClick={handleExit}
                disabled={uploading}
              >
                Save Draft & Exit
              </button>

              {hasUploadedFile && !file && (
                <button
                  type="button"
                  className="wizard-secondary"
                  onClick={handleContinueToReview}
                  disabled={uploading}
                >
                  Continue to Review
                </button>
              )}

              <button
                type="submit"
                className="wizard-primary"
                disabled={uploading || !file}
              >
                {uploading ? "Uploading..." : hasUploadedFile ? "Upload Replacement File" : "Upload File"}
              </button>
            </div>
          </div>

          <p className="wizard-footer-note">
            Your draft is saved. You can return to it later from My Manuscripts.
          </p>
        </form>
      )}

      {/* STEP 3: REVIEW AND SUBMIT */}
      {step === 3 && (
        <div className="wizard-form">
          <div className="wizard-section-heading">
            <h3>Review Your Submission</h3>
            <p>
              Check your manuscript information and uploaded document before submitting.
            </p>
          </div>

          <div className="wizard-manuscript-summary">
            <span className="wizard-summary-label">
              Manuscript ID
            </span>

            <strong>#{manuscriptId}</strong>
          </div>

          <div className="wizard-field">
            <label>Manuscript Title</label>
            <div className="wizard-review-value">
              {title}
            </div>
          </div>

          <div className="wizard-field">
            <label>Abstract</label>
            <div className="wizard-review-value wizard-review-abstract">
              {abstract}
            </div>
          </div>

          <div className="wizard-manuscript-summary">
            <span className="wizard-summary-label">
              Manuscript File
            </span>

            <strong>
              {displayFilename || (historyChecked ? "Original filename unavailable" : uploadedFilename) || "Filename unavailable"}
            </strong>

            <span>
              <span aria-hidden="true">✓ </span>
              File available
            </span>
          </div>

          <div className="wizard-alert">
            Please make sure all information is correct.
            Once submitted, the manuscript will enter the review workflow
            and can no longer be edited as a draft.
          </div>
          {getSelectedOnlineDraft?.(manuscriptId) && <p role="status">{getSelectedOnlineDraft(manuscriptId)}</p>}

          <div className="wizard-actions">
            <button
              type="button"
              className="wizard-secondary"
              onClick={() => {
                setStep(2);
                setError("");
                setMessage("");
              }}
              disabled={submitting}
            >
              ← Previous
            </button>

            <div className="wizard-action-group">
              <button
                type="button"
                className="wizard-secondary"
                onClick={() => {
                  setStep(1);
                  setError("");
                  setMessage("");
                }}
                disabled={submitting}
              >
                Edit Information
              </button>

              <button
                type="button"
                className="wizard-primary"
                onClick={handleSubmit}
                disabled={submitting || !hasUploadedFile}
              >
                {submitting ? "Submitting..." : "Submit Manuscript"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* STEP 4: COMPLETION */}
      {step === 4 && (
        <div className="wizard-form wizard-completion">
          <div className="wizard-completion-icon" aria-hidden="true">
            ✓
          </div>

          <h3>Manuscript Submitted Successfully!</h3>

          <p>
            Your manuscript has been submitted and is now in the
            submission workflow.
          </p>

          <div className="wizard-manuscript-summary">
            <span className="wizard-summary-label">
              Manuscript ID
            </span>

            <strong>#{manuscriptId}</strong>

            <span>{title}</span>
          </div>

          <p className="wizard-footer-note">
            You can track the progress of your manuscript from My Manuscripts.
          </p>

          <button
            type="button"
            className="wizard-primary"
            onClick={onClose}
          >
            Return to My Manuscripts
          </button>
        </div>
      )}
    </section>
  );
}

export default SubmissionWizard;
