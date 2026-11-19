import useManuscriptReturn from "./useManuscriptReturn";
import NotesPanel from "./NotesPanel";
import { authorPrompt } from "./participantPrompts";
import FormattingPanel from "./FormattingPanel";



import { useCallback, useEffect, useRef, useState } from "react";

import "./AuthorDashboard.css";
import SubmissionWizard from "./submission/SubmissionWizard";
import { metadataCounts } from "./submission/metadataCounts";

import NotificationBell from "./NotificationBell";

import InitialEditingPanel from "./InitialEditingPanel";

import AuthorAgreementPanel from "./AuthorAgreementPanel";

import FinalEditingPanel from "./FinalEditingPanel";

import ManuscriptProgress from "./ManuscriptProgress";

import useReturnRefresh from "./useReturnRefresh";

import OnlineDocumentEditor from "./OnlineDocumentEditor";

import OnlineDocxEditor from "./OnlineDocxEditor";

import { PRODUCT_DISPLAY_NAME, PRODUCT_SYSTEM_NAME } from "./branding";



import { API_URL } from "./api";

const MAX_FILE_SIZE = 10 * 1024 * 1024;



function AuthorDashboard({ user, token, registerManuscriptReturn }) {

  const [manuscripts, setManuscripts] = useState([]);

  const [progressId, setProgressId] = useState(null);

  const [detailDirty, setDetailDirty] = useState(false);

  const [onlineDirty, setOnlineDirty] = useState(false);

  const [progressRevision, setProgressRevision] = useState(0);

  const [currentStage, setCurrentStage] = useState(null);



  const [title, setTitle] = useState("");

  const [abstract, setAbstract] = useState("");

  const [showForm, setShowForm] = useState(false);
  const [wizardManuscript, setWizardManuscript] = useState(null);
  const [wizardState, setWizardState] = useState({ dirty: false, busy: false });



  const [loading, setLoading] = useState(true);

  const [submitting, setSubmitting] = useState(false);

  const [uploadingId, setUploadingId] = useState(null);

  const [filePickerOpen, setFilePickerOpen] = useState(false);

  const [downloadingId, setDownloadingId] = useState(null);



  // Revision form state

  const [editingId, setEditingId] = useState(null);

  const [revisionTitle, setRevisionTitle] = useState("");

  const [revisionAbstract, setRevisionAbstract] = useState("");

  const [revisionFile, setRevisionFile] = useState(null);

  const [selectedDocx, setSelectedDocx] = useState({});

  const [resubmitting, setResubmitting] = useState(false);



  // Draft editing and final submission

  const [draftEditingId, setDraftEditingId] = useState(null);

  const [draftTitle, setDraftTitle] = useState("");

  const [draftAbstract, setDraftAbstract] = useState("");
  const [draftFields, setDraftFields] = useState({ title: false, abstract: false });
  const [draftOriginal, setDraftOriginal] = useState({ title: "", abstract: "" });

  const [savingFields, setSavingFields] = useState({title:false, abstract:false});
  const [metadataErrors, setMetadataErrors] = useState({title:'', abstract:''});
  const metadataPending = useRef({title:false, abstract:false});
  const savingDraft = savingFields.title || savingFields.abstract;
  const metadataScope = useRef({token, progressId, mounted:true, generation:0});
  if (metadataScope.current.token !== token || metadataScope.current.progressId !== progressId) {
    metadataScope.current = {...metadataScope.current, token, progressId, generation:metadataScope.current.generation + 1};
    metadataPending.current = {title:false, abstract:false};
  }
  useEffect(() => { metadataScope.current.mounted = true; return () => { metadataScope.current.mounted = false; }; }, []);
  useEffect(() => { setSavingFields({title:false, abstract:false}); setMetadataErrors({title:'', abstract:''}); }, [token, progressId]);

  const [submittingDraftId, setSubmittingDraftId] = useState(null);



  const [error, setError] = useState("");

  const [message, setMessage] = useState("");



  const finalEditingPanel = useRef(null);

  const listVersion = useRef(0);

  const fileInputs = useRef({});

  const fileInteraction = useRef(false);

  const uploadInFlight = useRef(false);

  const onlineVersions = useRef({});

  const [selectionGenerations, setSelectionGenerations] = useState({});

  const selectionGenerationRef = useRef({});

  const revisionFileInput = useRef(null);





  // Read API responses and handle errors

  const readResponse = async (response, fallback) => {

    const contentType =

      response.headers.get("content-type") || "";



    let data = null;



    if (contentType.includes("application/json")) {

      data = await response.json();

    } else {

      const text = await response.text();

      data = { detail: text || fallback };

    }



    if (!response.ok) {

      const detail = data?.detail;



      throw new Error(

        typeof detail === "string"

          ? detail

          : Array.isArray(detail)

            ? detail.map((item) => item.msg || JSON.stringify(item)).join("; ")

            : fallback

      );

    }



    return data;

  };



  // Load manuscripts

  const loadManuscripts = useCallback(async () => {

    const version = ++listVersion.current;

    try {

      const response = await fetch(`${API_URL}/manuscripts/my`, {

        headers: {

          Authorization: `Bearer ${token}`,

        },

      });



      const contentType =

        response.headers.get("content-type") || "";



      const data = contentType.includes("application/json")

        ? await response.json()

        : null;



      if (!response.ok) {

        throw new Error(

          typeof data?.detail === "string"

            ? data.detail

            : "Failed to load manuscripts"

        );

      }



      if (!Array.isArray(data)) {

        throw new Error("Invalid manuscript data received.");

      }



      if (version !== listVersion.current || uploadInFlight.current) return false;

      setManuscripts(data);

      setProgressRevision(value => value + 1);

      return true;

    } catch (err) {

      if (version !== listVersion.current) return false;

      // Preserve existing manuscripts when a refresh fails.

      setError(err.message || "Failed to load manuscripts.");

      return false;

    } finally {

      if (version === listVersion.current) setLoading(false);

    }

  }, [token]);



  // Uploads affect one manuscript. Revalidate that record without replacing the

  // full list; share its request generation with full-list refreshes.

  const refreshUploadedManuscript = useCallback(async (manuscriptId) => {

    const version = ++listVersion.current;

    try {

      const response = await fetch(`${API_URL}/manuscripts/${manuscriptId}`, {

        headers: { Authorization: `Bearer ${token}` },

      });

      if (!response.ok) throw new Error('Could not update manuscript details.');

      const item = await response.json();

      if (!item || item.manuscript_id !== manuscriptId || typeof item.title !== 'string'

          || typeof item.abstract !== 'string' || typeof item.status !== 'string'

          || typeof item.created_at !== 'string' || typeof item.has_pdf !== 'boolean') {

        throw new Error('Invalid manuscript data received.');

      }

      if (version !== listVersion.current) return false;

      setManuscripts(previous => previous.map(existing => existing.manuscript_id === manuscriptId ? item : existing));

      setProgressRevision(value => value + 1);

      return true;

    } catch (err) {

      if (version === listVersion.current) setError(err.message || 'Could not update manuscript details.');

      return false;

    }

  }, [token]);



  useEffect(() => {

    const requestVersion = listVersion;



    loadManuscripts();



    return () => {

      requestVersion.current++;

    };

  }, [loadManuscripts]);

  // Do not refresh the manuscript list while viewing progress or editing.

  useReturnRefresh(

    loadManuscripts,

    progressId !== null || detailDirty || onlineDirty ||

    submitting || resubmitting || savingDraft ||

    filePickerOpen || uploadingId !== null || submittingDraftId !== null

  );



  const refreshAfterAgreement = async () => {

    const results = await Promise.allSettled([

      loadManuscripts(),

      finalEditingPanel.current?.refresh() ?? Promise.reject(new Error("Final editing panel unavailable")),

    ]);

    if (results.some(result => result.status === "rejected" || result.value === false)) {

      throw new Error("Could not refresh all panels");

    }

  };



  // Create manuscript

  const handleSubmit = async (event) => {

    event.preventDefault();



    if (submitting) return;



    if (!title.trim() || !abstract.trim()) {

      setError("Title and abstract cannot be empty.");

      return;

    }



    setSubmitting(true);

    setError("");

    setMessage("");



    try {

      const response = await fetch(`${API_URL}/manuscripts/`, {

        method: "POST",

        headers: {

          "Content-Type": "application/json",

          Authorization: `Bearer ${token}`,

        },

        body: JSON.stringify({

          title: title.trim(),

          abstract: abstract.trim(),

        }),

      });



      await readResponse(response, "Failed to save draft");



      setTitle("");

      setAbstract("");

      setShowForm(false);



      await loadManuscripts();



      setMessage("Draft saved successfully. Upload a PDF or Word file before submitting it.");

    } catch (err) {

      setError(err.message || "Failed to save draft.");

    } finally {

      setSubmitting(false);

    }

  };




  // Create a persistent draft for the submission wizard.
  const handleWizardCreateDraft = async ({ title, abstract }) => {
    const response = await fetch(`${API_URL}/manuscripts/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ title, abstract }),
    });

    const manuscript = await readResponse(
      response,
      "Failed to create manuscript draft"
    );

    await loadManuscripts();
    return manuscript;
  };

  // Update an existing draft when the author returns to Step 1.
  const handleWizardUpdateDraft = async (manuscriptId, data) => {
    const response = await fetch(
      `${API_URL}/manuscripts/${manuscriptId}`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(data),
      }
    );

    const manuscript = await readResponse(
      response,
      "Failed to update manuscript draft"
    );

    await loadManuscripts();
    return manuscript;
  };

  // Reuse the existing upload and refresh functions.
  const handleWizardUploadFile = async (manuscriptId, file) => {
    await uploadManuscriptFile(manuscriptId, file);
    return await refreshUploadedManuscript(manuscriptId);
  };

  const startDraftEdit = (manuscript, field) => {
    setDraftEditingId(manuscript.manuscript_id);
    if (field === 'title') setDraftTitle(manuscript.title || '');
    if (field === 'abstract') setDraftAbstract(manuscript.abstract || '');
    setDraftOriginal(previous => ({...previous, [field]: manuscript[field] || ''}));
    setDraftFields(previous => ({...previous, [field]: true}));
    setMetadataErrors(previous => ({...previous, [field]: ''}));
    setError("");
    setMessage("");
  };

  const cancelDraftEdit = (field = null) => {
    if (!field) { setDraftEditingId(null); setDraftFields({title:false,abstract:false}); setDraftTitle(""); setDraftAbstract(""); setMetadataErrors({title:'',abstract:''}); return; }
    setDraftFields(previous => ({...previous, [field]: false}));
    setMetadataErrors(previous => ({...previous, [field]: ''}));
  };

  const handleSaveDraft = async (event, manuscriptId, field) => {
    event.preventDefault();
    if (metadataPending.current[field]) return;

    const value = field === 'title' ? draftTitle : draftAbstract;
    if (!value.trim()) {
      setMetadataErrors(previous => ({...previous, [field]: `${field === 'title' ? 'Title' : 'Abstract'} cannot be empty.`}));
      return;
    }
    if (field === 'title' && metadataCounts(value.trim()).characters > 255) {
      setMetadataErrors(previous => ({...previous, title:'Title must not exceed 255 characters.'}));
      return;
    }

    metadataPending.current[field] = true;
    setSavingFields(previous => ({...previous, [field]: true}));
    setMetadataErrors(previous => ({...previous, [field]: ''}));
    setMessage("");
    const generation = metadataScope.current.generation;
    const isCurrent = () => metadataScope.current.mounted && metadataScope.current.generation === generation && metadataScope.current.token === token && metadataScope.current.progressId === manuscriptId;

    try {
      if (!globalThis.crypto?.subtle) throw new Error('Secure metadata comparison is unavailable. Reload in a secure browser context.');
      const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(draftOriginal[field]));
      if (!isCurrent()) return;
      const expected = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
      const response = await fetch(`${API_URL}/manuscripts/${manuscriptId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "X-Expected-Metadata-SHA256": expected,
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ [field]: value.trim() }),
      });

      await readResponse(response, "Failed to update draft");
      if (!isCurrent()) return;
      cancelDraftEdit(field);

      const refreshed = await loadManuscripts();
      if (!isCurrent()) return;

      setMessage(
        refreshed
          ? `${field === 'title' ? 'Title' : 'Abstract'} updated successfully.`
          : `${field === 'title' ? 'Title' : 'Abstract'} updated, but the list could not be refreshed.`
      );
    } catch (err) {
      if (isCurrent()) setMetadataErrors(previous => ({...previous, [field]: err.message || "Failed to update draft."}));
    } finally {
      if (isCurrent()) { metadataPending.current[field] = false; setSavingFields(previous => ({...previous, [field]: false})); }
    }
  };

  const hasConflictingDraftSelections = manuscriptId =>

    Boolean(selectedDocx[manuscriptId] && onlineVersions.current[manuscriptId]);



  const handleSubmitDraft = async (
    manuscript,
    { requireConfirmation = true } = {}
  ) => {
    const manuscriptId = manuscript.manuscript_id;

    if (submittingDraftId !== null || uploadingId !== null || savingDraft) {
      return false;
    }

    if (!manuscript.has_pdf) {
      setError("Upload a supported manuscript file before submitting.");
      return false;
    }

    const docxVersion = selectedDocx[manuscriptId];
    const txtVersion = onlineVersions.current[manuscriptId];

    if (hasConflictingDraftSelections(manuscriptId)) {
      setError("Please select only one online draft version.");
      return false;
    }

    if (
      requireConfirmation &&
      !window.confirm(
        `Submit Manuscript #${manuscriptId} for review? You will no longer be able to edit it as a draft.`
      )
    ) {
      return false;
    }

    setSubmittingDraftId(manuscriptId);
    setError("");
    setMessage("");

    try {
      const params = new URLSearchParams();

      if (docxVersion) {
        params.set("selected_docx_version", docxVersion);
      } else if (txtVersion) {
        params.set("expected_online_version", txtVersion);
      }

      const query = params.toString() ? `?${params.toString()}` : "";

      const response = await fetch(
        `${API_URL}/manuscripts/${manuscriptId}/submit${query}`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        }
      );

      await readResponse(response, "Failed to submit manuscript");

      if (draftEditingId === manuscriptId) {
        cancelDraftEdit();
      }

      const refreshed = await loadManuscripts();

      setMessage(
        refreshed
          ? `Manuscript #${manuscriptId} submitted successfully!`
          : `Manuscript #${manuscriptId} submitted, but the list could not be refreshed.`
      );

      return true;
    } catch (err) {
      setError(err.message || "Failed to submit manuscript.");
      return false;
    } finally {
      setSubmittingDraftId(null);
    }
  };

  // Submit from the new submission wizard.
  const handleWizardSubmitDraft = async (manuscriptId) => {
    const manuscript = manuscripts.find(
      item => item.manuscript_id === manuscriptId
    );

    if (!manuscript) {
      setError("Manuscript not found. Please refresh and try again.");
      return false;
    }

    return await handleSubmitDraft(manuscript, {
      requireConfirmation: false,
    });
  };

  // Validate supported manuscript formats (PDF, DOCX, DOC)

  const validateManuscriptFile = (file) => {

    if (!file) {

      throw new Error("Please select a PDF, DOCX, DOC, or UTF-8 TXT file.");

    }



    const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();

    if (![".pdf", ".docx", ".doc", ".txt"].includes(extension)) {

      throw new Error("Only PDF, DOCX, DOC, and TXT files are allowed.");

    }



    if (file.size === 0) {

      throw new Error("The manuscript file is empty.");

    }



    if (file.size > MAX_FILE_SIZE) {

      throw new Error("Manuscript file exceeds the 10 MB limit.");

    }

  };



  // Shared manuscript upload request

  const uploadManuscriptFile = async (manuscriptId, file) => {

    validateManuscriptFile(file);



    const formData = new FormData();

    formData.append("file", file);



    const response = await fetch(

      `${API_URL}/manuscripts/${manuscriptId}/upload`,

      {

        method: "POST",

        headers: {

          Authorization: `Bearer ${token}`,

        },

        body: formData,

      }

    );



    const result = await readResponse(response, "Manuscript file upload failed");

    // A successful replacement invalidates callbacks from the previous source.

    const nextGeneration = (selectionGenerationRef.current[manuscriptId] ?? 0) + 1;

    selectionGenerationRef.current[manuscriptId] = nextGeneration;

    setSelectionGenerations(previous => ({...previous, [manuscriptId]: nextGeneration}));

    delete onlineVersions.current[manuscriptId];

    setSelectedDocx(previous => ({...previous, [manuscriptId]: null}));

    return result;

  };



  // Upload manuscript file for draft

  const handleUpload = async (manuscriptId, file) => {

    if (uploadInFlight.current) return;

    if (!file) { fileInteraction.current = false; return; }

    if (hasConflictingDraftSelections(manuscriptId)) {

      fileInteraction.current = false;

      setMessage("");

      setError("Please select only one online draft version.");

      if (fileInputs.current[manuscriptId]) fileInputs.current[manuscriptId].value = "";

      return;

    }

    try {

      validateManuscriptFile(file);

    } catch (err) {

      fileInteraction.current = false;

      setMessage("");

      setError(err.message || "Manuscript file upload failed.");

      if (fileInputs.current[manuscriptId]) fileInputs.current[manuscriptId].value = "";

      return;

    }



    uploadInFlight.current = true;

    // Invalidate reads started before this mutation; they may return old file data.

    listVersion.current++;



    setError("");

    setMessage("");

    setUploadingId(manuscriptId);



    try {

      await uploadManuscriptFile(manuscriptId, file);

      const refreshed = await refreshUploadedManuscript(manuscriptId);

      setMessage(

        refreshed

          ? `Manuscript file uploaded successfully for Manuscript #${manuscriptId}.`

          : `Manuscript file uploaded for Manuscript #${manuscriptId}, but the manuscript list could not be refreshed.`

      );

    } catch (err) {

      setError(err.message || "Manuscript file upload failed.");

    } finally {

      uploadInFlight.current = false;

      fileInteraction.current = false;

      setUploadingId(null);



      if (fileInputs.current[manuscriptId]) {

        fileInputs.current[manuscriptId].value = "";

      }

    }

  };



  // Download manuscript in its original format

  const handleDownload = async (manuscriptId) => {

    if (downloadingId !== null) return;



    setError("");

    setMessage("");

    setDownloadingId(manuscriptId);



    try {

      const response = await fetch(

        `${API_URL}/manuscripts/${manuscriptId}/download`,

        {

          headers: {

            Authorization: `Bearer ${token}`,

          },

        }

      );



      if (!response.ok) {

        await readResponse(response, "Manuscript download failed");

        return;

      }



      const blob = await response.blob();

      if (blob.size === 0) {

        throw new Error("Downloaded manuscript file is empty.");

      }

      const link = document.createElement("a");

      const contentType = (response.headers.get("content-type") || "")

        .split(";")[0].trim().toLowerCase();

      const extensionsByMime = {

        "application/pdf": ".pdf",

        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",

        "application/msword": ".doc",

        "text/plain": ".txt",

      };

      const disposition = response.headers.get("content-disposition") || "";

      const filenameMatch = disposition.match(/filename\*?=(?:UTF-8''|")?([^;"]+)/i);

      const headerFilename = filenameMatch?.[1]?.trim();

      const headerExtension = headerFilename?.match(/\.(pdf|docx|doc|txt)$/i)?.[0]?.toLowerCase();

      const extension = headerExtension || extensionsByMime[contentType];

      if (!extension) {

        throw new Error("Unsupported manuscript download format.");

      }

      const url = URL.createObjectURL(blob);

      link.href = url;

      link.download = `manuscript_${manuscriptId}${extension}`;



      document.body.appendChild(link);

      link.click();

      link.remove();



      setTimeout(() => URL.revokeObjectURL(url), 1000);

    } catch (err) {

      setError(err.message || "Manuscript download failed.");

    } finally {

      setDownloadingId(null);

    }

  };



  // Open revision form

  const startRevision = (manuscript) => {

    setEditingId(manuscript.manuscript_id);

    setRevisionTitle(manuscript.title);

    setRevisionAbstract(manuscript.abstract);

    setRevisionFile(null);



    setError("");

    setMessage("");

  };



  // Close revision form

  const cancelRevision = () => {

    setEditingId(null);

    setRevisionTitle("");

    setRevisionAbstract("");

    setRevisionFile(null);



    if (revisionFileInput.current) {

      revisionFileInput.current.value = "";

    }

  };



  // Resubmit revised manuscript

  const handleResubmit = async (event, manuscriptId) => {

    event.preventDefault();



    if (resubmitting) return;

    if (hasConflictingDraftSelections(manuscriptId)) {

      setError("Please select only one online draft version.");

      return;

    }



    if (!revisionTitle.trim() || !revisionAbstract.trim()) {

      setError("Title and abstract cannot be empty.");

      return;

    }



    // Validate before starting either API operation



    try {

      if (!revisionFile && !selectedDocx[manuscriptId]) {

        setError("Please select a revised PDF or Word file before resubmitting.");

        return;

      }



      if (revisionFile) validateManuscriptFile(revisionFile);

    } catch (err) {

      setError(err.message);

      return;

    }





    setResubmitting(true);

    setError("");

    setMessage("");



    let manuscriptFileUploaded = false;



    try {

      // Upload replacement manuscript file before changing manuscript status



        if (revisionFile) {

          await uploadManuscriptFile(manuscriptId, revisionFile);

          manuscriptFileUploaded = true;

        }





      // Resubmit updated title and abstract

      const response = await fetch(

        `${API_URL}/manuscripts/${manuscriptId}/resubmit${revisionFile ? '' : `?selected_docx_version=${encodeURIComponent(selectedDocx[manuscriptId])}`}`,

        {

          method: "POST",

          headers: {

            "Content-Type": "application/json",

            Authorization: `Bearer ${token}`,

          },

          body: JSON.stringify({

            title: revisionTitle.trim(),

            abstract: revisionAbstract.trim(),

          }),

        }

      );



      await readResponse(response, "Manuscript resubmission failed");



      cancelRevision();

      setSelectedDocx(previous => ({...previous, [manuscriptId]: null}));



      const refreshed = await loadManuscripts();

      setMessage(

        refreshed

          ? `Manuscript #${manuscriptId} resubmitted successfully!`

          : `Manuscript #${manuscriptId} resubmitted, but the manuscript list could not be refreshed.`

      );

    } catch (err) {

      const prefix = manuscriptFileUploaded

        ? "The revised manuscript file was uploaded, but resubmission failed. "

        : "";



      setError(

        prefix + (err.message || "Manuscript resubmission failed.")

      );

    } finally {

      setResubmitting(false);

    }

  };



  // Dashboard statistics

  const draftCount = manuscripts.filter((manuscript) => manuscript.status === "draft").length;



  const acceptedCount = manuscripts.filter(

    (manuscript) => manuscript.status === "accepted"

  ).length;



  const submittedCount = manuscripts.filter(

    (manuscript) => manuscript.status === "submitted"

  ).length;



  const revisionCount = manuscripts.filter(

    (manuscript) => manuscript.status === "revision_required"

  ).length;



  const returnToManuscripts = () => {
    if (showForm && wizardState.busy) return false;
    if ((detailDirty || onlineDirty || editingId !== null || draftFields.title || draftFields.abstract || (showForm && wizardState.dirty)) && !window.confirm('Discard unsaved manuscript edits?')) return false;
    setEditingId(null); setDraftEditingId(null); setDraftFields({title:false,abstract:false}); setDetailDirty(false); setOnlineDirty(false); setCurrentStage(null); setProgressId(null); setShowForm(false); setWizardManuscript(null);
    return true;
  };
  useManuscriptReturn(registerManuscriptReturn, returnToManuscripts);

  const handleNotificationNavigate = (notification) => {

    const manuscriptId = notification.manuscript_id;

    if (!manuscripts.some(item => item.manuscript_id === manuscriptId)) return;
    if (showForm && (wizardState.busy || (wizardState.dirty && !window.confirm('Leave the submission wizard and discard unsaved changes?')))) return;
    if (showForm) { setShowForm(false); setWizardManuscript(null); }

    if (progressId !== null && progressId !== manuscriptId && (detailDirty || onlineDirty || editingId !== null || draftFields.title || draftFields.abstract) && !window.confirm('Discard unsaved manuscript edits?')) return;

    setEditingId(null); setDraftEditingId(null); setDraftFields({title:false,abstract:false}); setDetailDirty(false); setOnlineDirty(false); setCurrentStage(null); setProgressId(manuscriptId);

  };



  return (

    <div className="dashboard-page">

      <header className="dashboard-header">

        <div>

          <h1>{PRODUCT_DISPLAY_NAME} {PRODUCT_SYSTEM_NAME}</h1>

          <p>Author Dashboard · {user.name}</p>

        </div>





        <div

          style={{

            display: "flex",

            alignItems: "center",

            gap: "12px",

          }}

        >

          <NotificationBell

            token={token}

            onNavigate={handleNotificationNavigate}

          />







        </div>



      </header>



      <main className="dashboard-main">

        <h2>Welcome, {user.name}!</h2>



        <p className="dashboard-description">

          Manage your manuscripts and track submission status.

        </p>







        <div className={`author-content-layout${progressId !== null ? " has-workspace" : ""}`}>

          <div className="author-primary-content">

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



        <section className={`manuscript-section ${progressId !== null ? "manuscript-detail-section" : ""}`} data-sidebar-target="manuscripts" data-workspace={progressId !== null ? "selected" : undefined}>

          <div className="section-header">

            {progressId === null && <h2>My Manuscripts</h2>}



            {progressId === null && !showForm && <button

              type="button"

              className="new-submission-button"

              disabled={submitting}

              onClick={() => {
                if (showForm) {
                  setShowForm(false);
                  setWizardManuscript(null);
                } else {
                  setWizardManuscript(null);
                  setShowForm(true);
                }
              }}

            >

              {showForm ? "Cancel" : "+ New Submission"}

            </button>}

          </div>



          {showForm && (
            <SubmissionWizard
              key={wizardManuscript?.manuscript_id ?? "new"}
              initialManuscript={wizardManuscript}
              onStateChange={setWizardState}
              onCreateDraft={handleWizardCreateDraft}
              onUpdateDraft={handleWizardUpdateDraft}
              onUploadFile={handleWizardUploadFile}
              onSubmitDraft={handleWizardSubmitDraft}
              onClose={() => {
                setShowForm(false);
                setWizardManuscript(null);
              }}
            />
          )}





          {showForm ? null : loading ? (

            <p>Loading manuscripts...</p>

          ) : manuscripts.length === 0 ? (

            <p>No manuscripts or drafts yet.</p>

          ) : (

            <div className="manuscript-list">

              {manuscripts.filter(manuscript => progressId === null || manuscript.manuscript_id === progressId).map((manuscript) => {

                const manuscriptId = manuscript.manuscript_id;

                const editorGeneration = selectionGenerations[manuscriptId] ?? 0;



                const needsRevision =

                  manuscript.status === "revision_required";

                const isDraft = manuscript.status === "draft";

                const isDraftEditing = draftEditingId === manuscriptId;



                const isEditing = editingId === manuscriptId;



                if (progressId === null) return (

                  <div id={`manuscript-${manuscriptId}`} className="manuscript-card" key={manuscriptId}>

                    <div className="manuscript-card-top"><h3>{manuscript.title}</h3>

                      <span className={`status-badge ${manuscript.status}`}>{manuscript.status?.replaceAll('_', ' ')}</span></div>

                    <p>Manuscript #{manuscriptId}</p>

                    <button type="button" className="download-button" onClick={() => {

                if (showForm && (wizardState.busy || (wizardState.dirty && !window.confirm('Leave the submission wizard and discard unsaved changes?')))) return;
                setShowForm(false); setWizardManuscript(null);
                setCurrentStage(null);

                setProgressId(manuscriptId);

              }}>Open manuscript</button>

                  </div>

                );





                return (

                  <div

                    id={`manuscript-${manuscriptId}`}

                    className="manuscript-card"

                    key={manuscriptId}

                    onChangeCapture={event => { if (event.target.type !== 'file' && !event.target.closest('[data-online-editor]') && !event.target.closest('[data-metadata-editor]')) setDetailDirty(true); }}

                  >



                    <button type="button" className="manuscript-back" onClick={() => {

                      if ((detailDirty || onlineDirty || editingId === manuscriptId || draftFields.title || draftFields.abstract) && !window.confirm('Discard unsaved manuscript edits?')) return;

                      setEditingId(null); setDraftEditingId(null); setDraftFields({title:false,abstract:false}); setDetailDirty(false); setOnlineDirty(false); setProgressId(null);

                    }}>Back to Manuscripts</button>



                    <div className="manuscript-card-top">
                      <h3 className="manuscript-detail-title">{manuscript.title?.trim() || `Manuscript #${manuscriptId}`}</h3>
                      <span

                        className={`status-badge ${manuscript.status}`}

                      >

                        {typeof manuscript.status === "string" ? manuscript.status.replaceAll("_", " ") : "Unknown"}

                      </span>

                    </div>



                    {manuscript.title?.trim() && <p className="manuscript-id">

                      Manuscript #{manuscriptId}

                    </p>}
                    <details className="workspace-context"><summary>Private Notes</summary><NotesPanel manuscriptId={manuscriptId} token={token} /></details>
          {progressId !== null && !showForm && (
            <section
              className="author-workflows author-workflows-progress"
              key={`progress-${progressId}`}
              aria-label="Manuscript progress"
            >
              <div className="author-wizard-progress">
                <p className="progress-next"><strong>Next action:</strong> {authorPrompt(manuscript, Boolean(error))}</p>
                <ManuscriptProgress showTitle={false} showNextAction={false}
                  key={`progress-${progressId}`}
                  manuscriptId={progressId}
                  token={token}
                  revision={progressRevision}
                  suspendRefreshRef={fileInteraction}
                  onStageChange={setCurrentStage}
                />
              </div>
            </section>
          )}





                    <div
                      className="manuscript-section-heading"
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: "16px",
                        flexWrap: "wrap",
                        marginTop: "20px",
                        marginBottom: "12px"
                      }}
                    >
                      <h4 style={{ margin: 0 }}>Manuscript Information</h4>

                      {isDraft && <div className="manuscript-actions">
                        {!draftFields.title && <button type="button" className="upload-button" disabled={savingFields.title} onClick={() => startDraftEdit(manuscript, 'title')}>Edit Title</button>}
                        {!draftFields.abstract && <button type="button" className="upload-button" disabled={savingFields.abstract} onClick={() => startDraftEdit(manuscript, 'abstract')}>Edit Abstract</button>}
                      </div>}
                    </div>

                    {isDraft && isDraftEditing && draftFields.title && <form data-metadata-editor className="submission-form" onSubmit={event => handleSaveDraft(event, manuscriptId, 'title')}>
                      <label htmlFor={`draft-title-${manuscriptId}`}>Title</label>
                      <input id={`draft-title-${manuscriptId}`} value={draftTitle} onChange={event => setDraftTitle(event.target.value)} disabled={savingFields.title} required />
                      <p>{metadataCounts(draftTitle).characters}/255 characters</p>
                      {metadataErrors.title && <p role="alert">{metadataErrors.title}</p>}
                      <div className="manuscript-actions"><button type="submit" className="upload-button" disabled={savingFields.title}>{savingFields.title ? 'Saving Title...' : 'Save Title'}</button><button type="button" className="download-button" disabled={savingFields.title} onClick={() => cancelDraftEdit('title')}>Cancel Title</button></div>
                    </form>}
                    {isDraft && isDraftEditing && draftFields.abstract ? <form data-metadata-editor className="submission-form" onSubmit={event => handleSaveDraft(event, manuscriptId, 'abstract')}>
                      <label htmlFor={`draft-abstract-${manuscriptId}`}>Abstract</label>
                      <textarea id={`draft-abstract-${manuscriptId}`} value={draftAbstract} onChange={event => setDraftAbstract(event.target.value)} rows={5} disabled={savingFields.abstract} required />
                      <p>{metadataCounts(draftAbstract).words} words · {metadataCounts(draftAbstract).characters} characters (display count)</p>
                      {metadataErrors.abstract && <p role="alert">{metadataErrors.abstract}</p>}
                      <div className="manuscript-actions"><button type="submit" className="upload-button" disabled={savingFields.abstract}>{savingFields.abstract ? 'Saving Abstract...' : 'Save Abstract'}</button><button type="button" className="download-button" disabled={savingFields.abstract} onClick={() => cancelDraftEdit('abstract')}>Cancel Abstract</button></div>
                    </form> : <p className="manuscript-abstract">{manuscript.abstract}</p>}



                    <p className="manuscript-date">

                      Created:{" "}

                      {new Date(

                        manuscript.created_at

                      ).toLocaleDateString()}

                    </p>



                    <p className="manuscript-date">

                      Manuscript file: {manuscript.has_pdf ? "Available" : "Not uploaded"}

                    </p>



                    <h4>Current Stage Actions</h4>

                    {manuscript.file_type === "txt" && ['draft', 'revision_required', 'initial_revision_required'].includes(manuscript.status) && <OnlineDocumentEditor key={`online-${manuscriptId}`} manuscriptId={manuscriptId} token={token} onDirtyChange={setOnlineDirty} onVersion={version => { if ((selectionGenerationRef.current[manuscriptId] ?? 0) !== editorGeneration) return; onlineVersions.current[manuscriptId] = version; if (version) setSelectedDocx(previous => ({...previous, [manuscriptId]: null})); }} />}

                    {manuscript.file_type === "docx" && ['draft', 'revision_required', 'initial_revision_required'].includes(manuscript.status) && <OnlineDocxEditor key={`docx-${manuscriptId}`} manuscriptId={manuscriptId} token={token} stage="author" onSelect={id => { if ((selectionGenerationRef.current[manuscriptId] ?? 0) !== editorGeneration) return; delete onlineVersions.current[manuscriptId]; setSelectedDocx(previous => ({...previous, [manuscriptId]: id})); setRevisionFile(null); if (revisionFileInput.current) revisionFileInput.current.value = ''; }} onDirtyChange={setOnlineDirty} />}

                    {manuscript.status === 'initial_revision_required' && selectedDocx[manuscriptId] && <button type="button" disabled={resubmitting} onClick={async () => { if (hasConflictingDraftSelections(manuscriptId)) { setError('Please select only one online draft version.'); return; } setResubmitting(true); setError(''); try { const response = await fetch(`${API_URL}/manuscripts/${manuscriptId}/initial-resubmit?selected_docx_version=${encodeURIComponent(selectedDocx[manuscriptId])}`, {method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:'{}'}); await readResponse(response,'Initial resubmission failed'); setSelectedDocx(previous => ({...previous,[manuscriptId]:null})); setMessage('Revision submitted for initial screening.'); await loadManuscripts(); } catch (e) { setError(e.message || 'Initial resubmission failed'); } finally { setResubmitting(false); } }}>Submit selected DOCX revision</button>}

                    <div className="manuscript-actions">

                      {isDraft && (

                        <>

                          <input

                            type="file"

                            accept=".pdf,.docx,.doc,.txt"

                            className="hidden-file-input"

                            ref={(element) => {

                              fileInputs.current[manuscriptId] = element;

                            }}

                            onChange={(event) => {

                              setFilePickerOpen(false);

                              handleUpload(

                                manuscriptId,

                                event.target.files?.[0]

                              );

                            }}

                            onCancel={() => {

                              fileInteraction.current = false;

                              setFilePickerOpen(false);

                            }}

                          />



                          <button

                            type="button"

                            className="upload-button file-upload-control"

                            disabled={uploadingId !== null}

                            onClick={() => {

                              fileInteraction.current = true;

                              setFilePickerOpen(true);

                              fileInputs.current[manuscriptId]?.click();

                            }}

                          >

                            {uploadingId === manuscriptId

                              ? "Uploading..."

                              : "Upload File"}

                          </button>

                        </>

                      )}



                      {(manuscript.has_pdf || isDraft) && (

                        <button

                          type="button"

                          className="download-button"

                          disabled={!manuscript.has_pdf || downloadingId !== null}

                          title={!manuscript.has_pdf ? "Upload a manuscript file before downloading" : "Download manuscript file"}

                          onClick={() => handleDownload(manuscriptId)}

                        >

                          {downloadingId === manuscriptId

                            ? "Downloading..."

                            : "Download File"}

                        </button>

                      )}



                      {isDraft && (

                        <>

                          <button
                            type="button"
                            className="upload-button"
                            disabled={
                              savingDraft ||
                              submittingDraftId !== null ||
                              uploadingId !== null
                            }
                            onClick={() => {
                              setWizardManuscript(manuscript);
                              setShowForm(true);
                              setError("");
                              setMessage("");
                            }}
                          >
                            Continue Submission
                          </button>

                          

                          <button

                            type="button"

                            className="upload-button"

                            disabled={!manuscript.has_pdf || submittingDraftId !== null || uploadingId !== null || savingDraft}

                            onClick={() => handleSubmitDraft(manuscript)}

                            title={!manuscript.has_pdf ? "Upload a PDF, DOCX, DOC, or TXT file before submitting" : "Submit for review"}

                          >

                            {submittingDraftId === manuscriptId ? "Submitting..." : "Submit Manuscript"}

                          </button>

                        </>

                      )}



                      {needsRevision && !isEditing && (

                        <button

                          type="button"

                          className="upload-button"

                          disabled={resubmitting}

                          onClick={() => startRevision(manuscript)}

                        >

                          Revise Manuscript

                        </button>

                      )}

                    </div>

                    {needsRevision && isEditing && (

                      <form

                        className="submission-form"

                        onSubmit={(event) =>

                          handleResubmit(event, manuscriptId)

                        }

                      >

                        <h3>

                          Revise Manuscript #{manuscriptId}

                        </h3>



                        <label

                          htmlFor={`revision-title-${manuscriptId}`}

                        >

                          Revised Title

                        </label>



                        <input

                          id={`revision-title-${manuscriptId}`}

                          type="text"

                          value={revisionTitle}

                          onChange={(event) =>

                            setRevisionTitle(event.target.value)

                          }

                          maxLength={255}

                          disabled={resubmitting}

                          required

                        />



                        <label

                          htmlFor={`revision-abstract-${manuscriptId}`}

                        >

                          Revised Abstract

                        </label>



                        <textarea

                          id={`revision-abstract-${manuscriptId}`}

                          value={revisionAbstract}

                          onChange={(event) =>

                            setRevisionAbstract(event.target.value)

                          }

                          rows={5}

                          disabled={resubmitting}

                          required

                        />



                        <label

                          htmlFor={`revision-file-${manuscriptId}`}

                        >

                          Revised manuscript file (PDF, DOCX, DOC, or UTF-8 TXT; required)

                        </label>



                        <input

                          id={`revision-file-${manuscriptId}`}

                          type="file"

                          accept=".pdf,.docx,.doc,.txt"

                          ref={revisionFileInput}

                          required={!selectedDocx[manuscriptId]}

                          disabled={resubmitting}

                          onChange={(event) => { setRevisionFile(event.target.files?.[0] || null); }}

                        />



                        <div className="manuscript-actions">

                          <button

                            type="submit"

                            className="upload-button"

                            disabled={resubmitting}

                          >

                            {resubmitting

                              ? "Resubmitting..."

                              : "Resubmit Manuscript"}

                          </button>



                          <button

                            type="button"

                            className="download-button"

                            onClick={cancelRevision}

                            disabled={resubmitting}

                          >

                            Cancel

                          </button>

                        </div>

                      </form>

                    )}

                  </div>

                );

              })}

            </div>

          )}

        </section>

        {progressId !== null && !showForm && (

          <section

            className="author-workflows"

            key={progressId}

            onChangeCapture={() => setDetailDirty(true)}

            aria-label="Manuscript workflow details"

          >



            <div className="author-stage-content">

              {currentStage === "Initial Editing" && (
                <InitialEditingPanel
                  role="author"
                  token={token}
                  manuscriptId={progressId}
                  onChanged={loadManuscripts}
                />
              )}

              {currentStage === "Author Agreement" && (
                <AuthorAgreementPanel
                  token={token}
                  manuscriptId={progressId}
                  onChanged={refreshAfterAgreement}
                />
              )}

              {currentStage === "Final Editing" && (
                <FinalEditingPanel
                  ref={finalEditingPanel}
                  role="author"
                  token={token}
                  manuscriptId={progressId}
                  onChanged={loadManuscripts}
                />
              )}

              {currentStage === "Formatting" && (
                <FormattingPanel
                  role="author"
                  token={token}
                  manuscriptId={progressId}
                  onChanged={loadManuscripts}
                />
              )}


            </div>

          </section>

        )}

          </div>

        {progressId === null && <aside className="author-statistics-sidebar" aria-label="Manuscript statistics">

          <details className="dashboard-collapsible">
            <summary>Statistics</summary>

          <div className="stats-grid">

          <div className="stat-card">

            <span>My Manuscripts</span>

            <strong>{manuscripts.length}</strong>

          </div>



          <div className="stat-card">

            <span>Drafts</span>

            <strong>{draftCount}</strong>

          </div>



          <div className="stat-card">

            <span>Accepted</span>

            <strong>{acceptedCount}</strong>

          </div>



          <div className="stat-card">

            <span>Submitted</span>

            <strong>{submittedCount}</strong>

          </div>



          <div className="stat-card">

            <span>Revision Required</span>

            <strong>{revisionCount}</strong>

          </div>

        </div>

          </details>

        </aside>}

        </div>

      </main>

    </div>

  );

}



export default AuthorDashboard;
