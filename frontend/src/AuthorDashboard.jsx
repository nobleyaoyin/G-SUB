import {displayError} from './displayError';
import {downloadFilename} from './documentNames';
import StatusBadge from './StatusBadge';
import './ManuscriptsListLayout.css';
import {workflowStatusLabel} from './workflowStatus';
import useStageProjection, {StageProjectionNotice} from './useStageProjection';
import CollapsibleStatistics from './CollapsibleStatistics';
import StageFilterControls, {StageFilterClear} from './StageFilterControls';
import ManuscriptTimeline from "./ManuscriptTimeline";
import AuthorGenerationHistory from "./AuthorGenerationHistory";
import useManuscriptReturn from "./useManuscriptReturn";
import NotesPanel from "./NotesPanel";
import { authorPrompt } from "./participantPrompts";
import FormattingPanel from "./FormattingPanel";



import { useCallback, useEffect, useRef, useState } from "react";

import "./AuthorDashboard.css";
import SubmissionWizard from "./submission/SubmissionWizard";
import GuidedSubmissionWizard from "./submission/GuidedSubmissionWizard";
import { metadataCounts } from "./submission/metadataCounts";

import NotificationBell from "./NotificationBell";
import AuthorOverview from "./AuthorOverview";
import AuthorNotificationCenter from "./AuthorNotificationCenter";
import { manuscriptDate, manuscriptGroup, selectManuscripts } from "./authorManuscriptView";
import { roleLabels } from "./roleLabels";

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



function AuthorDashboard({ user, token, accountControl, registerManuscriptReturn, section = 'manuscripts', onSectionChange }) {

  const [manuscripts, setManuscripts] = useState([]);
  const [manuscriptSearch, setManuscriptSearch] = useState('');
  const [manuscriptFilter, setManuscriptFilter] = useState('all');
  const [manuscriptSort, setManuscriptSort] = useState('recent');
  const [notificationSnapshot, setNotificationSnapshot] = useState(null);
  const receiveNotifications = useCallback(snapshot => setNotificationSnapshot(snapshot), []);
  const previousSection = useRef('dashboard');
  const observedSection = useRef(section);
  if (observedSection.current !== section) {
    if (section === 'notifications') previousSection.current = observedSection.current === 'manuscripts' ? 'manuscripts' : 'dashboard';
    observedSection.current = section;
  }

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

  const [downloadingId, setDownloadingId] = useState(null);



  // Revision form state

  const [editingId, setEditingId] = useState(null);

  const [revisionTitle, setRevisionTitle] = useState("");

  const [revisionAbstract, setRevisionAbstract] = useState("");

  const [revisionFile, setRevisionFile] = useState(null);

  const [selectedDocx, setSelectedDocx] = useState({});
  const [guidedDrafts, setGuidedDrafts] = useState({});

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

    (showForm && wizardState.busy) || uploadingId !== null || submittingDraftId !== null

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
  const handleWizardUploadFile = async (manuscriptId, file, requestId) => {
    if (hasConflictingDraftSelections(manuscriptId)) {
      throw new Error("Please select only one online draft version.");
    }
    if (uploadInFlight.current) throw new Error("A manuscript upload is already in progress.");
    uploadInFlight.current = true;
    listVersion.current++;
    setUploadingId(manuscriptId);
    try {
      const uploaded = await uploadManuscriptFile(manuscriptId, file, requestId);
      if (!await refreshUploadedManuscript(manuscriptId)) return false;
      return { versionId: uploaded?.version_id || null, filename: uploaded?.filename || null };
    } finally {
      uploadInFlight.current = false;
      setUploadingId(null);
    }
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

  const uploadManuscriptFile = async (manuscriptId, file, requestId) => {

    validateManuscriptFile(file);



    const formData = new FormData();

    formData.append("file", file);
    if (requestId) formData.append("request_id", requestId);



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

      const downloadName = downloadFilename(disposition);
      link.download = downloadName && downloadName.toLowerCase().endsWith(extension) ? downloadName : `manuscript_${manuscriptId}${extension}`;



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

        setError("Please select a revised PDF, DOCX, DOC, or UTF-8 TXT file before resubmitting.");

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
    onSectionChange?.('manuscripts');

  };



  const stageProjection = useStageProjection(manuscripts, token, manuscriptFilter);
  const wizardMode = !wizardManuscript || wizardManuscript.submission_draft_id || guidedDrafts[wizardManuscript.manuscript_id] ? 'guided' : 'legacy';
  const ActiveSubmissionWizard = wizardMode === 'legacy' ? SubmissionWizard : GuidedSubmissionWizard;

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
            onViewAll={onSectionChange ? () => { if (returnToManuscripts() !== false) onSectionChange('notifications'); } : undefined}
            onAuthorSnapshot={onSectionChange ? receiveNotifications : undefined}

          />
          {accountControl}







        </div>



      </header>



      <main className="dashboard-main">

        <h2>Welcome, {user.name}!</h2>



        <p className="dashboard-description">

          Manage your manuscripts and track submission status.

        </p>







        <div className={`author-content-layout${progressId !== null || (onSectionChange && (section !== 'dashboard' || showForm)) ? " has-workspace" : ""}${progressId !== null && !showForm ? " has-manuscript-detail" : ""}${progressId === null && !showForm && (!onSectionChange || section === "manuscripts") ? " has-manuscript-list" : ""}`}>

          <div className="author-primary-content">

        {error && (

          <div className="error-message" role="alert">

            {displayError(error)}

          </div>

        )}



        {message && (

          <div className="success-message" role="status">

            {message}

          </div>

        )}



        {onSectionChange && section === 'dashboard' && progressId === null && !showForm ? <AuthorOverview manuscripts={manuscripts} loading={loading} error={displayError(error)} onOpen={id => handleNotificationNavigate({manuscript_id:id})} onNavigate={onSectionChange} /> : onSectionChange && section === 'notifications' ? <AuthorNotificationCenter snapshot={notificationSnapshot} token={token} onOpen={handleNotificationNavigate} onBack={() => onSectionChange(previousSection.current)} /> : onSectionChange && section === 'profile' ? <section className="author-overview-card" aria-label="My profile"><h2>My Profile</h2><p><strong>Name:</strong> {user.name || 'Unavailable'}</p><p><strong>Email:</strong> {user.email || 'Unavailable'}</p><p><strong>Role:</strong> {roleLabels[user.role] || user.role || 'Unavailable'}</p><button type="button" className="download-button" onClick={() => onSectionChange('dashboard')}>Back to dashboard</button></section> : <section className={`manuscript-section ${progressId !== null ? "manuscript-detail-section" : ""}`} data-sidebar-target="manuscripts" data-workspace={progressId !== null ? "selected" : undefined}>

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

          {onSectionChange && progressId === null && !showForm && <div className="author-list-controls">
            <label>Search manuscripts <input type="search" value={manuscriptSearch} onChange={event=>setManuscriptSearch(event.target.value)} placeholder="Title or manuscript ID" /></label>
            <StageFilterControls value={manuscriptFilter} onChange={value => setManuscriptFilter(value || 'all')} items={stageProjection.items} />
            <label>Sort <select value={manuscriptSort} onChange={event=>setManuscriptSort(event.target.value)}><option value="recent">Most recently updated</option><option value="oldest">Oldest updated</option><option value="title">Title</option></select></label>
            <StageFilterClear onClear={() => {setManuscriptSearch('');setManuscriptFilter('all');setManuscriptSort('recent');}} />
            <p role="status">{stageProjection.loading || stageProjection.unavailable ? 'Result count unavailable' : `${selectManuscripts(stageProjection.items,manuscriptSearch,manuscriptFilter,manuscriptSort).length} matching results`}</p><small>When an update date is unavailable, sorting uses the creation date.</small><StageProjectionNotice projection={stageProjection} />
          </div>}



          {showForm && (wizardMode === 'guided' || wizardMode === 'legacy') && (
            <ActiveSubmissionWizard
              key={wizardManuscript?.manuscript_id ?? "new"}
              initialManuscript={wizardManuscript}
              initialDraftId={wizardManuscript ? (wizardManuscript.submission_draft_id || guidedDrafts[wizardManuscript.manuscript_id]) : null}
              onDraftLinked={async (manuscriptId,draftId)=>{setGuidedDrafts(previous=>({...previous,[manuscriptId]:draftId})); await loadManuscripts();}}
              onStateChange={setWizardState}
              onCreateDraft={handleWizardCreateDraft}
              onUpdateDraft={handleWizardUpdateDraft}
              onUploadFile={handleWizardUploadFile}
              onConfirmedUpload={id=>{const generation=(selectionGenerationRef.current[id]??0)+1;selectionGenerationRef.current[id]=generation;setSelectionGenerations(previous=>({...previous,[id]:generation}));delete onlineVersions.current[id];setSelectedDocx(previous=>({...previous,[id]:null}));setOnlineDirty(false);}}
              onSubmitDraft={handleWizardSubmitDraft}
              token={token}
              onDownloadCurrent={handleDownload}
              downloadBusy={downloadingId !== null}
              documentDirty={onlineDirty}
              getSelectedOnlineDraft={id => selectedDocx[id] ? 'A saved DOCX draft is selected for submission.' : onlineVersions.current[id] ? 'A saved TXT draft is selected for submission.' : null}
              getSubmissionParameters={id => selectedDocx[id] ? {selected_docx_version:selectedDocx[id]} : onlineVersions.current[id] ? {expected_online_version:onlineVersions.current[id]} : {}}
              onSubmissionComplete={loadManuscripts}
              onOpenManuscript={id => { setShowForm(false); setWizardManuscript(null); setOnlineDirty(false); setProgressId(id); onSectionChange?.('manuscripts'); }}
              onDiscardDocumentEdits={() => setOnlineDirty(false)}
              renderDocumentEditor={(manuscriptId, format) => {
                const generation = selectionGenerationRef.current[manuscriptId] ?? 0;
                if (format === 'txt') return <OnlineDocumentEditor key={`wizard-txt-${manuscriptId}-${generation}`} manuscriptId={manuscriptId} token={token} onDirtyChange={setOnlineDirty} onVersion={version => { if ((selectionGenerationRef.current[manuscriptId] ?? 0) !== generation) return; onlineVersions.current[manuscriptId] = version; if (version) setSelectedDocx(previous => ({...previous, [manuscriptId]: null})); }} />;
                if (format === 'docx') return <OnlineDocxEditor key={`wizard-docx-${manuscriptId}-${generation}`} manuscriptId={manuscriptId} token={token} stage="author" showUnavailable onSelect={id => { if ((selectionGenerationRef.current[manuscriptId] ?? 0) !== generation) return; delete onlineVersions.current[manuscriptId]; setSelectedDocx(previous => ({...previous, [manuscriptId]: id})); }} onDirtyChange={setOnlineDirty} />;
                return null;
              }}
              onClose={() => {
                setShowForm(false);
                setWizardManuscript(null);
                setOnlineDirty(false);
              }}
            />
          )}





          {showForm ? null : loading ? (

            <p>Loading manuscripts...</p>

          ) : manuscripts.length === 0 ? (

            <p>No manuscripts or drafts yet.</p>

          ) : (

            <div className="manuscript-list">

              {progressId === null && onSectionChange && !stageProjection.loading && !stageProjection.unavailable && selectManuscripts(stageProjection.items,manuscriptSearch,manuscriptFilter,manuscriptSort).length === 0 && <p>No manuscripts match these filters.</p>}

              {(progressId === null && onSectionChange ? selectManuscripts(stageProjection.items,manuscriptSearch,manuscriptFilter,manuscriptSort) : manuscripts.filter(manuscript => progressId === null || manuscript.manuscript_id === progressId)).map((manuscript) => {

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

                      <StatusBadge status={manuscript.status} /></div>

                    <p>Manuscript #{manuscriptId}</p>
                    {onSectionChange && <p>Created: {manuscriptDate(manuscript.created_at)}{manuscript.updated_at ? ` · Updated: ${manuscriptDate(manuscript.updated_at)}` : ''}</p>}

                    <button type="button" className="manuscript-open-button" onClick={() => {

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

                    }}>Back to manuscripts</button>



                    <div className="manuscript-card-top">
                      <h3 className="manuscript-detail-title">{manuscript.title?.trim() || `Manuscript #${manuscriptId}`}</h3>
                      <StatusBadge status={manuscript.status} />

                    </div>



                    {manuscript.title?.trim() && <p className="manuscript-id">

                      Manuscript #{manuscriptId}

                    </p>}
                    <section aria-label="Manuscript Abstract" className="author-abstract-section">
                    <div className="manuscript-section-heading">
                      <h4>Manuscript Abstract</h4>

                      {isDraft && <div className="manuscript-actions">
                        {!draftFields.title && <button type="button" className="upload-button" disabled={savingFields.title} onClick={() => startDraftEdit(manuscript, 'title')}>Edit title</button>}
                        {!draftFields.abstract && <button type="button" className="upload-button" disabled={savingFields.abstract} onClick={() => startDraftEdit(manuscript, 'abstract')}>Edit abstract</button>}
                      </div>}
                    </div>

                    {isDraft && isDraftEditing && draftFields.title && <form data-metadata-editor className="submission-form" onSubmit={event => handleSaveDraft(event, manuscriptId, 'title')}>
                      <label htmlFor={`draft-title-${manuscriptId}`}>Title</label>
                      <input id={`draft-title-${manuscriptId}`} value={draftTitle} onChange={event => setDraftTitle(event.target.value)} disabled={savingFields.title} required />
                      <p>{metadataCounts(draftTitle).characters}/255 characters</p>
                      {metadataErrors.title && <p role="alert">{metadataErrors.title}</p>}
                      <div className="manuscript-actions"><button type="submit" className="upload-button" disabled={savingFields.title}>{savingFields.title ? 'Saving title...' : 'Save title'}</button><button type="button" className="download-button" disabled={savingFields.title} onClick={() => cancelDraftEdit('title')}>Cancel title</button></div>
                    </form>}
                    {isDraft && isDraftEditing && draftFields.abstract ? <form data-metadata-editor className="submission-form" onSubmit={event => handleSaveDraft(event, manuscriptId, 'abstract')}>
                      <label htmlFor={`draft-abstract-${manuscriptId}`}>Abstract</label>
                      <textarea id={`draft-abstract-${manuscriptId}`} value={draftAbstract} onChange={event => setDraftAbstract(event.target.value)} rows={5} disabled={savingFields.abstract} required />
                      <p>{metadataCounts(draftAbstract).words} words · {metadataCounts(draftAbstract).characters} characters (display count)</p>
                      {metadataErrors.abstract && <p role="alert">{metadataErrors.abstract}</p>}
                      <div className="manuscript-actions"><button type="submit" className="upload-button" disabled={savingFields.abstract}>{savingFields.abstract ? 'Saving abstract...' : 'Save abstract'}</button><button type="button" className="download-button" disabled={savingFields.abstract} onClick={() => cancelDraftEdit('abstract')}>Cancel abstract</button></div>
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



                    </section>
                    <details className="workspace-context"><summary>Private Notes</summary><NotesPanel manuscriptId={manuscriptId} token={token} /></details>
                    <AuthorGenerationHistory key={`generation-${manuscriptId}`} manuscriptId={manuscriptId} token={token} revision={progressRevision} />
          {progressId !== null && !showForm && (
            <section
              className="author-workflows author-workflows-progress"
              key={`progress-${progressId}`}
              aria-label="Manuscript progress"
            >
              <div className="author-wizard-progress">
                <ManuscriptProgress showTitle={false}
                  key={`progress-${progressId}`}
                  manuscriptId={progressId}
                  token={token}
                  fallbackAction={authorPrompt(manuscript, Boolean(error))}
                  taskDisabled={Boolean(error)}
                  revision={progressRevision}
                  onStageChange={setCurrentStage}
                />
              </div>
              <ManuscriptTimeline manuscriptId={progressId} token={token} revision={progressRevision} />
            </section>
          )}





                    <h4>Next Step</h4>

                    {manuscript.file_type === "txt" && ['revision_required', 'initial_revision_required'].includes(manuscript.status) && <OnlineDocumentEditor key={`online-${manuscriptId}`} manuscriptId={manuscriptId} token={token} onDirtyChange={setOnlineDirty} onVersion={version => { if ((selectionGenerationRef.current[manuscriptId] ?? 0) !== editorGeneration) return; onlineVersions.current[manuscriptId] = version; if (version) setSelectedDocx(previous => ({...previous, [manuscriptId]: null})); }} />}

                    {manuscript.file_type === "docx" && ['revision_required', 'initial_revision_required'].includes(manuscript.status) && <OnlineDocxEditor key={`docx-${manuscriptId}`} manuscriptId={manuscriptId} token={token} stage="author" onSelect={id => { if ((selectionGenerationRef.current[manuscriptId] ?? 0) !== editorGeneration) return; delete onlineVersions.current[manuscriptId]; setSelectedDocx(previous => ({...previous, [manuscriptId]: id})); setRevisionFile(null); if (revisionFileInput.current) revisionFileInput.current.value = ''; }} onDirtyChange={setOnlineDirty} />}

                    {manuscript.status === 'initial_revision_required' && selectedDocx[manuscriptId] && <button type="button" disabled={resubmitting} onClick={async () => { if (hasConflictingDraftSelections(manuscriptId)) { setError('Please select only one online draft version.'); return; } setResubmitting(true); setError(''); try { const response = await fetch(`${API_URL}/manuscripts/${manuscriptId}/initial-resubmit?selected_docx_version=${encodeURIComponent(selectedDocx[manuscriptId])}`, {method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:'{}'}); await readResponse(response,'Initial resubmission failed'); setSelectedDocx(previous => ({...previous,[manuscriptId]:null})); setMessage('Revision submitted for initial screening.'); await loadManuscripts(); } catch (e) { setError(e.message || 'Initial resubmission failed'); } finally { setResubmitting(false); } }}>Submit selected DOCX revision</button>}

                    <div className="manuscript-actions" id={`author-manuscript-actions-${manuscriptId}`}>

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
                              if ((detailDirty || onlineDirty || editingId !== null || draftFields.title || draftFields.abstract) && !window.confirm('Discard unsaved manuscript edits?')) return;
                              setEditingId(null); setDraftEditingId(null); setDraftFields({title:false, abstract:false}); setDetailDirty(false); setOnlineDirty(false);
                              setWizardManuscript(manuscript);
                              setShowForm(true);
                              setError("");
                              setMessage("");
                            }}
                          >
                            Continue Process
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

                          Revise Editor Manuscript

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

                          Revise Editor Manuscript #{manuscriptId}

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



                        {manuscript.has_pdf && <button type="button" className="download-button" disabled={downloadingId !== null} onClick={() => handleDownload(manuscriptId)}>{downloadingId === manuscriptId ? "Downloading..." : "Download Current File"}</button>}

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

        </section>}

        {progressId !== null && !showForm && (

          <section

            className="author-workflows"

            key={progressId}

            onChangeCapture={() => setDetailDirty(true)}

            aria-label="Manuscript workflow details"

          >



            <div className="author-stage-content">

              {currentStage === "Initial Editing" && (
                <div id={`initial-editing-action-${progressId}`}>
                <InitialEditingPanel
                  role="author"
                  token={token}
                  manuscriptId={progressId}
                  onChanged={loadManuscripts}
                />
                </div>
              )}

              {currentStage === "Author Agreement" && (
                <div id={`author-agreement-action-${progressId}`}>
                <AuthorAgreementPanel
                  token={token}
                  manuscriptId={progressId}
                  onChanged={refreshAfterAgreement}
                />
                </div>
              )}

              {currentStage === "Final Editing" && (
                <div id={`final-editing-action-${progressId}`}>
                <FinalEditingPanel
                  ref={finalEditingPanel}
                  role="author"
                  token={token}
                  manuscriptId={progressId}
                  onChanged={loadManuscripts}
                />
                </div>
              )}

              {['Formatting', 'Proofing'].includes(currentStage) && (
                <div id={`author-formatting-action-${progressId}`}>
                <FormattingPanel
                  role="author"
                  token={token}
                  manuscriptId={progressId}
                  onChanged={loadManuscripts}
                />
                </div>
              )}


            </div>

          </section>

        )}

          </div>

        {(!onSectionChange || (['dashboard', 'manuscripts'].includes(section) && !showForm)) && <aside className="author-statistics-sidebar" aria-label="Manuscript statistics">

          <CollapsibleStatistics className="dashboard-collapsible">

          {error ? <p>Statistics are unavailable.</p> : loading ? <p role="status">Loading statistics…</p> : <div className="stats-grid">

          <div className="stat-card">

            <span>{onSectionChange ? 'Total manuscripts' : 'My Manuscripts'}</span>

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

            <span>{onSectionChange ? 'Submitted / in progress' : 'Submitted'}</span>

            <strong>{onSectionChange ? manuscripts.filter(m => manuscriptGroup(m.status) === 'progress').length : submittedCount}</strong>

          </div>



          <div className="stat-card">

            <span>Revision required</span>

            <strong>{onSectionChange ? manuscripts.filter(m => manuscriptGroup(m.status) === 'revision').length : revisionCount}</strong>

          </div>

          {onSectionChange && <div className="stat-card"><span>Rejected</span><strong>{manuscripts.filter(m => manuscriptGroup(m.status) === 'rejected').length}</strong></div>}

        </div>}

          </CollapsibleStatistics>

        </aside>}

        </div>

      </main>

    </div>

  );

}



export default AuthorDashboard;
