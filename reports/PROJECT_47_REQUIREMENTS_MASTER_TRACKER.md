# Project 47 Requirements Master Tracker

## Executive summary

Not Started: 0 · In Progress: 32 · Implemented: 0 · Tested: 15 · Accepted: 0.

**Batch 17C carryover (Batch 18):** A local read-only dry-run diagnostic inventories reservations, private storage objects and grant/revocation references. It does not reconcile, restore, delete or record cleanup outcomes; uncertain objects require further operational design. See the Batch 18 report.

The baseline is the exact existing [authoritative audit](G_SUB_Complete_Requirements_Audit_1-47.md). Each original heading and full corresponding audit entry is reproduced verbatim below; its historical status is part of the quotation and is not this tracker’s current status. The audit entry is the only wording supplied in that document; it is not presented as a verbatim transcript of a professor recording. Source-level references below are prior-audit evidence and may be stale; unverified items remain In Progress, including items with no work started, until current source and scope are reviewed. Tested means the relevant synthetic frontend checks were run in this task; it does not mean browser, end-to-end or user acceptance.

Original reference inspected: [four-card design image](../references/WhatsApp%20Image%202026-11-10%20at%208.18.37%20PM.jpeg). The image says “Journal Management System — Select Your Role” and includes descriptions; requirements 2, 4 and 5 explicitly request changes to that older design. It does not identify the five workspace boxes. The prototype and workflow PDFs remain supplementary references; per-item references below do not assert that a screenshot demonstrates acceptance.

## Unresolved professor/product decisions

- #6 identities and interactions of the five right-side boxes; #11 incomplete click instruction; #29 purpose of the EIC middle panel.
- #17 word-count thresholds, keyword units and supported extraction behavior; #18 intended JALA reference.
- #36 permitted bypasses and reasons; #38 policy text/acceptance; #39–42 delivery and stage communication audiences and rules.
- #43 approved agreement content; #44–46 precise generation and document-transfer semantics; #47 visual acceptance reference.

## Individual requirements

### 1. General / Copy Editor — Implemented

**Original audit wording and evidence (verbatim):**

- **Evidence:** `frontend/src/roleLabels.js` maps `editor` to `General / Copy Editor`; `RoleSelection.jsx` uses the label. `App.jsx` also labels the formatter dashboard this way.
- **FE:** retain and audit other editor labels for context, including `EditorDashboard.jsx` and `SharedSidebar.jsx`. **BE/data:** no change; account role remains `editor`. **Security/deps:** avoid changing `User.role` or role checks; related to 3/27. **Tests:** `RoleSelection.test.jsx`, `App.test.jsx`, `SharedSidebar.test.jsx` plus labels on actual editor login.

**Tracker status:** Tested.
**Professor/source reference:** [authoritative audit, requirement 1](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.


**Batch 24 status change:** In Progress → Tested. Shared editor label is preserved in the chooser, sidebar and actual Editor dashboard. Synthetic editor login and focused role tests passed. See [Batch 24 report](G_SUB_47_BATCH_24_QUICK_WINS_COMPLETION_REPORT.md).

### 2. Remove front-page role descriptions — Implemented

**Original audit wording and evidence (verbatim):**

- **Evidence:** `RoleSelection.jsx` renders each role's icon and name, not per-card descriptions; the generic account-permissions note remains. `RoleSelection.css` contains unused `.role-description` styling.
- **FE:** preserve current cards; remove leftover styling only if appropriate. Do not automatically remove the useful permissions note. **BE/data:** none. **Security/deps:** role text cannot grant rights; 1/3/5. **Tests:** `RoleSelection.test.jsx` checks card content and accessible names.

**Tracker status:** Tested.
**Professor/source reference:** [authoritative audit, requirement 2](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.


**Batch 24 status change:** In Progress → Tested. Role-card descriptions were removed while the account-permissions note and accessible names remain; desktop chooser and keyboard interaction verified. See [Batch 24 report](G_SUB_47_BATCH_24_QUICK_WINS_COMPLETION_REPORT.md).

### 3. Group Formatter with Editor — Implemented

**Original audit wording and evidence (verbatim):**

- **Evidence:** `RoleSelection.jsx` has only eic/editor/reviewer/author; `roleLabels.js` maps both `editor` and `formatter` to the combined label; `App.jsx:41` `matchesSelectedRole` accepts a formatter through editor selection and dispatches the authenticated formatter to `FormattingPanel`. `app/routers/formatting.py` permits assigned editor or formatter accounts.
- **FE:** keep exactly one combined card and the existing compatibility path. **BE/data:** preserve the separate stored role and invitation checks; no migration. **Security/deps:** do not elevate either account; formatting access still depends on invitation. **Tests:** `RoleSelection.test.jsx`, `App.test.jsx`, `FormattingPanel.navigation.test.jsx`, `tests/test_editor_formatting_merge.py`, `tests/test_formatting.py`.

**Tracker status:** Tested.
**Professor/source reference:** [authoritative audit, requirement 3](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.


**Batch 24 status change:** In Progress → Tested. The four-card chooser retains the shared Editor entry. Synthetic Formatter login, authorized formatting workspace and isolated formatting authorization tests passed. See [Batch 24 report](G_SUB_47_BATCH_24_QUICK_WINS_COMPLETION_REPORT.md).

### 4. Manuscript Management System branding — Implemented on chooser

**Original audit wording and evidence (verbatim):**

- **Evidence:** `RoleSelection.jsx` says “Manuscript management system”; `frontend/src/branding.js` holds product branding; `App.jsx` has manuscript-submission-system headings. A project-wide active UI string audit is needed for remaining old labels.
- **FE:** unify only actual user-visible legacy instances via `RoleSelection.jsx`, `App.jsx`, `branding.js` where appropriate. **BE/data:** none. **Security/deps:** avoid altering product identity in tokens, URLs or APIs; 47. **Tests:** role/auth heading snapshots or accessible text assertions.

**Tracker status:** Tested.
**Professor/source reference:** [authoritative audit, requirement 4](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.


**Batch 24 status change:** In Progress → Tested. G-SUB branding now consistently uses the Manuscript Management System descriptor in the chooser, dashboard headings, sidebar, sign-in footer and browser title; desktop and frontend tests passed. See [Batch 24 report](G_SUB_47_BATCH_24_QUICK_WINS_COMPLETION_REPORT.md).

### 5. Remove visible “Select Your Role” — Implemented

**Original audit wording and evidence (verbatim):**

- **Evidence:** `RoleSelection.jsx` has no visible heading with that phrase; the role grid retains `aria-label="Choose a sign-in role"`.
- **FE:** keep the accessible label. **BE/data:** none. **Security/deps:** preserve readable role context and keyboard access; 1–3. **Tests:** `RoleSelection.test.jsx` asserts no visible old heading and accessible grid.

**Tracker status:** Tested.
**Professor/source reference:** [authoritative audit, requirement 5](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.


**Batch 24 status change:** In Progress → Tested. The visible old heading remains absent; the role group retains its accessible name and keyboard focus, verified in tests and desktop Chromium. See [Batch 24 report](G_SUB_47_BATCH_24_QUICK_WINS_COMPLETION_REPORT.md).

### 6. Five horizontally scrolling boxes with sidebar — Needs clarification

**Original audit wording and evidence (verbatim):**

- **Evidence:** `RoleSelection.jsx` renders four cards; authenticated `SharedSidebar.jsx` provides Dashboard, Manuscripts, Notifications. `ManuscriptProgress.jsx` renders nine stages, and `EICDashboard.jsx` uses a two-column list/detail grid. No inspected source unambiguously identifies the professor's five boxes. Formatter must not become a fifth login card.
- **FE:** identify the five actual dashboard/content boxes with a desktop mockup and preserve sidebar and keyboard-scroll affordances; likely files `App.jsx`, `SharedSidebar.jsx/.css`, affected dashboard CSS. **BE/data:** none unless boxes need data. **Security/deps:** do not expose cross-manuscript or restricted content; 12/23/30. **Tests:** five intended items, focus and horizontal scrolling, sidebar navigation, desktop visual inspection. No implementation should invent the fifth box.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 6](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 7. Faint completed status word — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `ManuscriptProgress.css` dims `.progress-completed .progress-stage-row > span` (stage name), whereas the separate status `<strong>` uses shared styling; CSS cascade must be checked in the browser. `ManuscriptProgress.jsx` emits Completed/Current/Upcoming.
- **FE:** style completed **status word** with a quieter but readable token; do not fade the whole stage or imply uncertain stages completed. **BE/data:** none. **Security/deps:** role-safe evidence from progress endpoint; 8/20/26. **Tests:** `ManuscriptProgress.test.jsx`, visual and computed contrast of completed/current/unknown states.

**Tracker status:** Tested.
**Professor/source reference:** [authoritative audit, requirement 7](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** `npx vitest run src/ManuscriptProgress.test.jsx src/AuthorDashboard.layout.test.jsx src/EICDashboard.navigation.test.jsx src/EditorDashboard.navigation.test.jsx src/ReviewerDashboard.blind.test.jsx src/FormattingPanel.navigation.test.jsx` — 6 files, 58 tests passed.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Batch 1 — progress UI.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 8. Three circle styles — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `ManuscriptProgress.css` has solid blue completed, blue outlined current and gray outlined pending; `unknown` exists separately in `ManuscriptProgress.jsx`. Black outline has not been demonstrated.
- **FE:** map pending to readable black outline, current to blue outline, completed to solid blue after confirming semantics; keep unknown visually and textually distinguishable. **BE/data:** none. **Security/deps:** do not collapse unknown into completion; 7/9/20. **Tests:** `ManuscriptProgress.test.jsx`, rendered styles and text labels for all four API states.

**Tracker status:** Tested.
**Professor/source reference:** [authoritative audit, requirement 8](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** `npx vitest run src/ManuscriptProgress.test.jsx src/AuthorDashboard.layout.test.jsx src/EICDashboard.navigation.test.jsx src/EditorDashboard.navigation.test.jsx src/ReviewerDashboard.blind.test.jsx src/FormattingPanel.navigation.test.jsx` — 6 files, 58 tests passed.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Batch 1 — progress UI.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 9. Larger progress circles — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `ManuscriptProgress.css` `.progress-timeline > li::before` is 20×20 px; connectors/checkmark are positioned relative to it.
- **FE:** increase modestly and adjust connector and checkmark offsets, without clipping. **BE/data:** none. **Security/deps:** retain non-color state and keyboard controls; 8/20. **Tests:** desktop screenshot and keyboard layout at long stage names, computed size and focus.

**Tracker status:** Tested.
**Professor/source reference:** [authoritative audit, requirement 9](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** `npx vitest run src/ManuscriptProgress.test.jsx src/AuthorDashboard.layout.test.jsx src/EICDashboard.navigation.test.jsx src/EditorDashboard.navigation.test.jsx src/ReviewerDashboard.blind.test.jsx src/FormattingPanel.navigation.test.jsx` — 6 files, 58 tests passed.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Batch 1 — progress UI.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 10. Replace My Manuscripts with title in context — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `AuthorDashboard.jsx:1355` switches heading from My Manuscripts to Manuscript Details on selection; `:1513` displays title lower down, after progress. Other role detail headers have similar local headings. Sidebar's Manuscripts is a list destination, not a selected title.
- **FE:** use the selected authorized title as the detail workspace heading, retain list/sidebar label; use ID fallback for withheld reviewer metadata. `AuthorDashboard.jsx`, role dashboards, `FormattingPanel.jsx`. **BE/data:** none. **Security/deps:** do not reveal a hidden title; 22/23. **Tests:** author and blind reviewer headings, sidebar destination, single title.

**Tracker status:** Tested.
**Professor/source reference:** [authoritative audit, requirement 10](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** Batch 2 focused role/navigation suite: 10 files, 85 tests passed; see [Batch 2 report](G_SUB_47_BATCH_2_WORKSPACE_IMPLEMENTATION_REPORT.md) for exact command and limitations.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Batch 2 — selected-workspace/navigation review.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 2 update:** Batch 2 adds blank-title ID fallbacks for selected Author, Editor and EIC views. Reviewer/Formatter and final-editor browser confirmation remain open.


**Batch 25 update:** In Progress → Tested. The five selected-workspace headings and A/B/A navigation were exercised in synthetic Chromium, including protected Reviewer fallback. Editor formatting-only and Formatter blank-title fallbacks were added and tested. See [Batch 25 report](G_SUB_47_BATCH_25_WORKSPACE_COMPLETION_REPORT.md).

### 11. Clicking manuscript box — Needs clarification

**Original audit wording and evidence (verbatim):**

- **Evidence:** author opens via `Open manuscript`, EIC list buttons call `open(id)`, editor `toggleActions`, reviewer selects an assignment, and formatter `setSelectedItem`; these reveal selected workspaces rather than navigating routes. See respective dashboard JSX and `FormattingPanel.jsx`.
- **FE:** keep these semantics until the incomplete instruction is clarified; if a larger click target is wanted, use a valid accessible button, not nested interactive controls. **BE/data:** none for navigation. **Security/deps:** preserve selected ID, stale-request and dirty-form guards; 23/25/33. **Tests:** role-specific navigation and keyboard activation with multiple manuscripts.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 11](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 12. Collapse nonessential boxes — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** EIC notes, general comments and history use `<details>` (`EICDashboard.jsx:160,167,449`); editor context/statistics and reviewer statistics also have disclosures; author statistics is collapsible. Essential stage actions remain inline.
- **FE:** use role-appropriate accessible disclosures for ancillary context after identifying priority; retain open errors and actions. Dashboard JSX/CSS, `InitialEditingPanel.jsx`, `FinalEditingPanel.jsx`, `FormattingPanel.jsx`. **BE/data:** none. **Security/deps:** hiding does not authorize or filter data; 13/30/34. **Tests:** keyboard, disclosure states, validation alerts, dirty inputs retained while collapsed.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 12](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** Batch 3 focused role/workspace suite: 7 files and 64 tests passed; exact command and limitations are in the [Batch 3 report](G_SUB_47_BATCH_3_DASHBOARD_LAYOUT_IMPLEMENTATION_REPORT.md).
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Batch 2 — selected-workspace/navigation review.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 3 update:** Batch 3 retains existing native secondary disclosures and tests draft preservation after collapsing/reopening in Author, Editor and EIC. Browser keyboard behavior and visible error handling when a panel is closed remain unverified.


**Batch 25 update:** Remains In Progress. Native stage disclosures and Enter/Space behavior were exercised in Chromium; closed-panel validation/error visibility and all role-specific disclosure cases are not fully verified. See [Batch 25 report](G_SUB_47_BATCH_25_WORKSPACE_COMPLETION_REPORT.md).


**Batch 26 update:** Remains In Progress. Native disclosures, keyboard interaction and dirty note retention were exercised in synthetic tests/browser. Errors and failed/pending operations inside every collapsed panel have not been fully verified and may still be hidden. See [Batch 26 report](G_SUB_47_BATCH_26_FOUR_REQUIREMENTS_COMPLETION_REPORT.md).


**Batch 27 update:** Remains In Progress. Notes and Staff General Comments disclosures now reopen on load or save errors and retain drafts; a real EIC server validation failure and focused tests were verified. Error and pending-state acceptance remains incomplete across all other role-specific sections. See [Batch 27 report](G_SUB_47_BATCH_27_THREE_REQUIREMENTS_COMPLETION_REPORT.md).


**Batch 28 update:** Remains In Progress. Existing notes/comment error disclosures and synthetic five-role navigation were exercised; the full five-role pending/failure/error-visibility matrix remains unverified. See [Batch 28 report](G_SUB_47_BATCH_28_WORKSPACE_PROGRESS_COMPLETION_REPORT.md).

### 13. Notes and General Comments near top — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** EIC `EICDashboard.jsx:160–172` places them after overview; editor uses context disclosures near actions (`EditorDashboard.jsx:525,703`); author has `NotesPanel` (`AuthorDashboard.jsx:1609`). `GeneralCommentsPanel` is staff-only; `app/routers/general_comments.py:_require_staff_access` excludes author/reviewer, and `personal_notes.py` enforces individual ownership.
- **FE:** place authorized panels near selected header, label private versus staff-shared clearly; do not show unauthorized panel. **BE/data:** none for relocation. **Security/deps:** never broaden recipients; 23/34/42. **Tests:** `tests/test_general_comments.py`, `tests/test_personal_notes.py`, role rendering and note privacy.

**Tracker status:** Tested.
**Professor/source reference:** [authoritative audit, requirement 13](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** Batch 3 focused role/workspace suite: 7 files and 64 tests passed; exact command and limitations are in the [Batch 3 report](G_SUB_47_BATCH_3_DASHBOARD_LAYOUT_IMPLEMENTATION_REPORT.md).
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Batch 2 — selected-workspace/navigation review.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 3 update:** Private Notes moved above progress in Author; existing Editor notes and staff comments moved ahead of overview. EIC panels retain their separate labels. Synthetic draft and placement checks passed; no backend access policy changed.


**Batch 25 update:** Remains In Progress. EIC Private Notes and Staff Shared Comments were moved ahead of distribution; notes/comments authorization tests passed, but formatter-specific and full cross-role browser privacy acceptance remain incomplete. See [Batch 25 report](G_SUB_47_BATCH_25_WORKSPACE_COMPLETION_REPORT.md).


**Batch 26 update:** Remains In Progress. Standalone Formatter now receives existing personal-note and staff-comment panels only for an accepted assignment; draft text participates in navigation protection. Synthetic positive/negative API tests passed; complete five-role browser privacy acceptance remains open. See [Batch 26 report](G_SUB_47_BATCH_26_FOUR_REQUIREMENTS_COMPLETION_REPORT.md).


**Batch 27 update:** In Progress → Tested. Existing authorized panels were verified with synthetic A/B/A personal and staff content for Author, EIC, Editor and accepted Formatter, protected Reviewer view, pending Formatter and Author/Reviewer denials, backend ownership checks and late-response tests. See [Batch 27 report](G_SUB_47_BATCH_27_THREE_REQUIREMENTS_COMPLETION_REPORT.md).

### 14. Timeline — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `ManuscriptProgress.jsx` has a status timeline; EIC history separately enumerates scans, invitations, submissions and decisions in `EICDashboard.jsx:449–605`. No single chronological cross-workflow event feed was found.
- **FE:** add a collapsible selected-manuscript timeline with stage, date and event category; keep it separate from private comments. **BE/data:** derive a read-only role-filtered view from existing records or add `GET /manuscripts/{id}/timeline`; no migration for a partial derived timeline. Additive event persistence only if missing events must be captured prospectively. **Security/deps:** do not invent absent timestamps or expose private identities; 34/45/46. **Tests:** order, missing timestamps, legacy unknowns, role leakage and cross-manuscript denial.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 14](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Batch 2 — selected-workspace/navigation review.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.


**Batch 25 update:** Remains In Progress. Existing EIC Activity History is labeled Timeline and includes timestamped recorded initial/final invitation responses; role-filtered cross-workflow projections and all requested event types remain incomplete. See [Batch 25 report](G_SUB_47_BATCH_25_WORKSPACE_COMPLETION_REPORT.md).


**Batch 26 update:** Remains In Progress. Existing EIC Activity History includes matching authorized formatting submissions and recorded publication when loaded, without comment text; a full role-filtered timeline and distribution/revocation coverage are not implemented. See [Batch 26 report](G_SUB_47_BATCH_26_FOUR_REQUIREMENTS_COMPLETION_REPORT.md).


**Batch 28 update:** Remains In Progress. EIC Activity History now shows timestamped grant and revocation events from the existing authorized ledger; the requested complete role-filtered timelines and event coverage are not implemented. See [Batch 28 report](G_SUB_47_BATCH_28_WORKSPACE_PROGRESS_COMPLETION_REPORT.md).

### 15. Document operations — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `AuthorDashboard.jsx` handles upload/download, draft submit and revision; `InitialEditingPanel.jsx`, `FinalEditingPanel.jsx`, `FormattingPanel.jsx` expose stage artifacts; `OnlineDocumentEditor.jsx` and `OnlineDocxEditor.jsx` handle text/DOCX editing. `GET /manuscripts/{id}/download`, `/versions`, revision and `/initial-resubmit` are in `app/routers/manuscripts.py`; stage-specific download routes are in `eic.py` and `formatting.py`. `Review` has comments/recommendation and no reviewed-file path (`app/models.py:272`; `app/routers/reviews.py:40`).
- **FE:** create an action matrix by role and stage with upload, download, editable title/abstract and online document controls, submit, appropriate edited/formatted downloads and revision upload/submit. Distinguish reviewer comments from a reviewed document; do not add a misleading button. **BE/data:** reuse existing stage-specific APIs; reviewed-file upload/download needs new assignment-bound endpoints/model/storage if requested; preserve immutable versions. **Security/deps:** role, ownership, stage, format and round checks; 16/44–46. **Tests:** `tests/test_secure_word_uploads.py`, `test_multiformat_safe_subset.py`, `test_reviewer_download.py`, online editor and role workflow tests, failed upload and version preservation.

**Tracker status:** In Progress.

**Batch 18.1 update:** Batch 18.1 exercised four formats through synthetic upload, submit, two seeded revision states and historical downloads; ownership and selected staff controls passed. The author dashboard still has no general historical-version list and the entire editorial decision chain is not browser-verified. See Batch 18.1 report.

**Batch 18 update:** The existing upload/submit flow was exercised with a real synthetic TXT submission; broader requested file, revision and authorization coverage remains open. The seven-suite frontend run passed, while the requested legacy backend regression run had failures. See the Batch 18 report.
**Professor/source reference:** [authoritative audit, requirement 15](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 16. Separate Edit Abstract and Edit Title — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** author detail currently shows `Edit Title & Abstract` and saves both via `handleSaveDraft` (`AuthorDashboard.jsx:520,536,1562`); `ManuscriptUpdate` accepts optional title/abstract. TXT and DOCX online document editing are separate controls.
- **FE:** present two independent metadata actions, with field-specific save/cancel and unsaved-change guard; keep document editing and revision forms. **BE/data:** reuse `PATCH /manuscripts/{id}` and optional `ManuscriptUpdate`; ensure omitted field is not overwritten. No schema migration. **Security/deps:** ownership and allowed status remain server-side; 15/17. **Tests:** separate saves, race/cancel, preserve untouched value and online editing (`AuthorDashboard.layout.test.jsx`, conflict tests).

**Tracker status:** Tested.

**Batch 18 update:** Independent title and abstract editing now sends only the edited field, with an optional server compare-and-set check, stale-response guards and separate cancel controls. Focused automated checks and a real synthetic-browser save/resume flow passed; exhaustive concurrency and acceptance remain open.
**Professor/source reference:** [authoritative audit, requirement 16](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.


**Batch 25 update:** Remains In Progress. Existing field-specific PATCH saves were exercised independently in synthetic Chromium and focused tests passed; complete field-specific loading/error and concurrency acceptance remains unverified. See [Batch 25 report](G_SUB_47_BATCH_25_WORKSPACE_COMPLETION_REPORT.md).


**Batch 26 update:** Remains In Progress. Title and Abstract now have independent loading, errors and duplicate-request guards, with concurrent frontend tests and a real synthetic conflict browser flow. Full concurrent browser and failure/acceptance matrix remains unverified. See [Batch 26 report](G_SUB_47_BATCH_26_FOUR_REQUIREMENTS_COMPLETION_REPORT.md).


**Batch 27 update:** In Progress → Tested. The existing independent forms were verified in synthetic Chromium with concurrent real backend saves, both field conflicts, cancellation, server validation, persistence and switching manuscripts during a pending save; focused frontend and backend regression tests passed. See [Batch 27 report](G_SUB_47_BATCH_27_THREE_REQUIREMENTS_COMPLETION_REPORT.md).

### 17. Min/max abstract, body and keywords — Missing; thresholds unspecified

**Original audit wording and evidence (verbatim):**

- **Evidence:** `app/schemas.py:51–110` validates nonempty title/abstract and title length; `SubmissionWizard.jsx` checks nonempty metadata. `Manuscript` has title/abstract but no keywords field. `app/ai_prescreening.py` computes a heuristic word count for its analysis; `app/ai_docx_parser.py` is a bounded DOCX parser, not a universal authoritative body extractor. PDF/DOC/TXT/DOCX are accepted.
- **FE:** show live counts, limits and errors for abstract/keywords and verified body count when available; preserve save-as-draft where policy allows. **BE/data:** define identical tokenization, length limits, article types and validation on create/update plus every submission/resubmission path in `schemas.py`, `routers/manuscripts.py` and relevant online-version code. Add a backward-compatible keywords representation/migration if required; body extraction policy must explicitly handle PDF (including scanned), DOC, DOCX, TXT, parser failure and resource caps. Do not silently reject supported formats or trust client-reported counts. **Security/deps:** untrusted files, denial of service, stale selected version, historic drafts and privacy; 15/18/37. **Tests:** min/max boundaries, Unicode, all formats and unextractable cases, invalid direct API, version races and old records. Thresholds and keyword counting unit require approval.

**Tracker status:** In Progress.

**Batch 18 update:** The wizard displays informational abstract word and Unicode character counts and explicitly reports unavailable keywords/body counts. No unapproved limits, keywords schema or universal document extractor was introduced. Submission-wide validation and professor decisions remain open.
**Professor/source reference:** [authoritative audit, requirement 17](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 18. JALA-inspired submission — Partial; reference ambiguous

**Original audit wording and evidence (verbatim):**

- **Evidence:** `submission/SubmissionWizard.jsx` already implements Information → Upload → Review & Submit with saved draft, type/size checks and confirmation; `AuthorDashboard.jsx` supplies callbacks. “JALA” identifies multiple journals, e.g. the [Journal of Asian Linguistic Anthropology](https://jala.glocal-journals.link/) and the [Journal of the African Literature Association submission guidelines](https://www.africanlit.org/publications/old-jala/submission-guidelines.pdf). The intended journal and its current authenticated submission interface are not established.
- **FE:** retain wizard, improve step guidance, error summaries and review screen after the specific reference is supplied. **BE/data:** reuse draft/upload/submit; new metadata only if actually required and separately designed. **Security/deps:** avoid copying policies, requirements, branding, copyrighted content or external account integration; 17/37. **Tests:** `submission/SubmissionWizard.test.jsx`, author wizard tests, save/resume and direct API bypass. No claim of matching an uninspected submission system.

**Tracker status:** In Progress.

**Batch 18.1 update:** The isolated desktop browser uploaded and resubmitted a TXT revision into round 2; the editor workspace showed round 2. Full user acceptance and a visible historical-version interface remain open.

**Batch 18 update:** The existing three-step wizard was exercised in a real synthetic browser for draft creation, TXT upload, review and submission; separate draft save/resume was also exercised. Counts and the known 255-character title validation were added. Remaining required formats, revision and failure flows need verification.
**Professor/source reference:** [authoritative audit, requirement 18](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 19. Milestones label — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `ManuscriptProgress.jsx` renders “Stage Details” and “Stage Milestones”; the exact old phrase “Initial Editing Milestones” was not found in the active component. `initial_editing_progress` in `app/routers/manuscripts.py:949` supplies six steps.
- **FE:** replace nested labels with one “Milestones” heading; preserve stage accessible context. **BE/data:** none. **Security/deps:** retain role-safe steps; 20/21. **Tests:** `ManuscriptProgress.test.jsx` for heading and authorized steps.

**Tracker status:** Tested.
**Professor/source reference:** [authoritative audit, requirement 19](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** `npx vitest run src/ManuscriptProgress.test.jsx src/AuthorDashboard.layout.test.jsx src/EICDashboard.navigation.test.jsx src/EditorDashboard.navigation.test.jsx src/ReviewerDashboard.blind.test.jsx src/FormattingPanel.navigation.test.jsx` — 6 files, 58 tests passed.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Batch 1 — progress UI.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.


**Batch 28 update:** Remains Tested. The existing single Milestones heading and six Initial Editing steps were retained; focused frontend tests and a synthetic desktop disclosure were exercised. See [Batch 28 report](G_SUB_47_BATCH_28_WORKSPACE_PROGRESS_COMPLETION_REPORT.md).

### 20. Stage dropdowns — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `ManuscriptProgress.jsx` maps static stages and displays only active stage steps; `app/routers/manuscripts.py:853,1033` supplies nine stages, and steps only for Initial Editing to author/EIC.
- **FE:** accessible disclosure for each stage, including a truthful empty/unavailable state. **BE/data:** extend the existing `/manuscripts/{id}/progress` read model only for validated, role-filtered milestones for each stage; no inherent schema change. **Security/deps:** preserve unknown evidence, historical statuses, reviewer anonymity and formatter assignment; 7–9/19/21/31/33. **Tests:** `test_role_safe_progress.py`, `test_progress_completion_evidence.py`, `ManuscriptProgress.test.jsx`, all stages and keyboard disclosures.

**Tracker status:** In Progress.

**Batch 19.1 update:** All nine native disclosures were keyboard-tested in a synthetic Author browser. Role-safe backend tests passed, but all-role browser milestone and historical evidence coverage is incomplete.

**Batch 19 update:** Native disclosures retained for the nine existing stage records. Real-browser Enter and Space were exercised for all nine; the existing progress API still lacks verified milestone records for most stages. Scoped progress responses now prevent a previous token from rendering.
**Professor/source reference:** [authoritative audit, requirement 20](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** `npx vitest run src/ManuscriptProgress.test.jsx src/AuthorDashboard.layout.test.jsx src/EICDashboard.navigation.test.jsx src/EditorDashboard.navigation.test.jsx src/ReviewerDashboard.blind.test.jsx src/FormattingPanel.navigation.test.jsx` — 6 files, 58 tests passed.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Batch 1 — progress UI.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 21. Reduce progress repetition — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** progress repeats title/ID and round already shown by EIC/editor detail and uses Stage Details plus Stage Milestones; `ManuscriptProgress.jsx`, `EICDashboard.jsx:126–146`, `EditorDashboard.jsx:594–620`.
- **FE:** one title at workspace header, one round/status and next action; move milestone detail into disclosure. Retain error, unknown and local-publication caveat. **BE/data:** none. **Security/deps:** safe title fallback and data availability; 10/19/20/22. **Tests:** progress states and role workspace assertions.

**Tracker status:** In Progress.

**Batch 19.1 update:** Existing header hierarchy was retained. Browser switching was exercised across roles; exhaustive single status, round and action deduplication is not yet demonstrated.

**Batch 19 update:** Existing embedded title/next-action options and honest unknown/caveat states were retained; full cross-role elimination of status and round repetition is not certified.
**Professor/source reference:** [authoritative audit, requirement 21](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** `npx vitest run src/ManuscriptProgress.test.jsx src/AuthorDashboard.layout.test.jsx src/EICDashboard.navigation.test.jsx src/EditorDashboard.navigation.test.jsx src/ReviewerDashboard.blind.test.jsx src/FormattingPanel.navigation.test.jsx` — 6 files, 58 tests passed.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Batch 1 — progress UI.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.


**Batch 28 update:** Remains In Progress. EIC, Editor and Reviewer can suppress a duplicate review round in embedded progress; repeated missing-title ID labels were reduced. Comprehensive all-role, all-stage repetition acceptance remains open. See [Batch 28 report](G_SUB_47_BATCH_28_WORKSPACE_PROGRESS_COMPLETION_REPORT.md).

### 22. Title once at top — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** progress renders title, parent roles render title, and `InitialEditingPanel.jsx`, `FinalEditingPanel.jsx`, `FormattingPanel.jsx` can repeat it when embedded.
- **FE:** parent renders one authorized heading before progress; embedded panels suppress duplicate headings, standalone lists retain them. **BE/data:** none. **Security/deps:** reviewer protected mode may omit title; preserve ID and edit fields; 10/21/23. **Tests:** role-selected views, nested components and blind metadata.

**Tracker status:** In Progress.

**Batch 19.1 update:** Existing parent and embedded heading behavior was retained. Browser tests checked selected manuscript labels and protected reviewer title; comprehensive standalone and all-role title uniqueness remains open.

**Batch 19 update:** Existing explicit embedded title suppression was retained; five selected role views were opened in a synthetic browser, but exhaustive standalone and protected-title combinations were not browser-certified.
**Professor/source reference:** [authoritative audit, requirement 22](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** Batch 2 focused role/navigation suite: 10 files, 85 tests passed; see [Batch 2 report](G_SUB_47_BATCH_2_WORKSPACE_IMPLEMENTATION_REPORT.md) for exact command and limitations.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Batch 2 — selected-workspace/navigation review.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 2 update:** Existing embedded progress panels suppress titles; cross-role real-browser and nested editing-panel duplication remains unverified.

### 23. One manuscript per workspace — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** each dashboard filters a selected manuscript/assignment; author global statistics (`AuthorDashboard.jsx:2066`) and reviewer profile/statistics (`ReviewerDashboard.jsx:352–380`) remain outside selection, and global notifications can mention other manuscripts. EIC hides its list on selection; formatter filters `visibleItems`.
- **FE:** hide unrelated aggregates/list/profile in detail, pass selected IDs to nested panels, agree on notifications exception and list destinations. `AuthorDashboard.jsx`, `EditorDashboard.jsx`, `ReviewerDashboard.jsx`, `EICDashboard.jsx`, `FormattingPanel.jsx`, `App.jsx`. **BE/data:** no new access rights; retain checks in manuscript, assignment, formatting and comment routers. **Security/deps:** stale responses and reviewer round identity; 10/22/24/25. **Tests:** select A/B across roles, delayed A, assert no B content and correct permissions.

**Tracker status:** In Progress.

**Batch 19.1 update:** Synthetic browser A → B → A succeeded for all five roles. Editor dashboard/history and EIC overview now reject stale identity or selection responses and mismatched overview IDs; complete cross-role document/comment/round and delayed-response matrices remain open.

**Batch 19 update:** Formatting responses now use token, role and manuscript scope plus request sequencing; reviewer detail responses check the active assignment. Author A-to-B switching and a delayed formatting response were tested; delayed A-to-B-to-A scenarios across all roles remain open. Global notifications retain their existing separate behavior.
**Professor/source reference:** [authoritative audit, requirement 23](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** Batch 2 focused role/navigation suite: 10 files, 85 tests passed; see [Batch 2 report](G_SUB_47_BATCH_2_WORKSPACE_IMPLEMENTATION_REPORT.md) for exact command and limitations.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Batch 2 — selected-workspace/navigation review.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 2 update:** Existing A/B, stale-response and reviewer fixtures ran; not all roles and delayed combinations have full coverage or browser verification.

### 24. New Draft only on main page — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** author label is `+ New Submission` (`AuthorDashboard.jsx:1353–1380`), unconditional when a manuscript is selected; wizard creates a persistent draft.
- **FE:** show only on agreed main/list page and make wizard/detail mutually exclusive with dirty guards. **BE/data:** none. **Security/deps:** preserve draft ownership and resumability; 11/23/25. **Tests:** `AuthorDashboard.submission-wizard.test.jsx`, `AuthorDashboard.layout.test.jsx`, unsaved wizard navigation.

**Tracker status:** In Progress.

**Batch 19.1 update:** Synthetic Author browser verified list-only New Submission and dirty wizard cancel/confirm, with existing submission tests passing. Selected file, title and abstract dirty browser variants are not all covered.

**Batch 19 update:** The Author submission wizard and selected detail are now mutually exclusive; the New Submission action is hidden during the wizard. Unsaved information and file selection prompt before close or sidebar navigation, and busy operations block leaving. Browser cancellation and confirmation passed.
**Professor/source reference:** [authoritative audit, requirement 24](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** Batch 2 focused role/navigation suite: 10 files, 85 tests passed; see [Batch 2 report](G_SUB_47_BATCH_2_WORKSPACE_IMPLEMENTATION_REPORT.md) for exact command and limitations.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Batch 2 — selected-workspace/navigation review.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 2 update:** Author layout and submission wizard suites ran; verify end-to-end saved-draft resume and dirty cancellation in a browser.

### 25. Back to Manuscripts in sidebar — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** inline Back buttons exist in all five role views; `SharedSidebar.jsx` has Manuscripts but `App.jsx` merely scrolls to a DOM target and does not reliably clear role-owned selection.
- **FE:** add a context-sensitive sidebar return callback delegated to each owning view; handle canceled/confirmed dirty state and focus list on success. `App.jsx`, `SharedSidebar.jsx/.css`, role dashboards and `FormattingPanel.jsx`. **BE/data:** none. **Security/deps:** preserve async guards and notification navigation; 11/23/24/33. **Tests:** `App.sidebar.test.jsx`, `SharedSidebar.test.jsx`, dashboard navigation tests and cancellation across roles.

**Tracker status:** Tested.

**Batch 19.1 update:** All five synthetic roles returned through the sidebar and kept dirty input after cancellation, then returned after confirmation. Automated reviewer tests also verify confirmed discard; complete focus, notification and all role-specific async combinations remain open.

**Batch 19 update:** Existing dashboard-owned return callbacks and list-focus behavior were retained. Reviewer confirmed discard now clears the selected assignment draft. Author sidebar dirty cancellation/confirmation and return were tested in Chromium; equivalent browser interactions across all roles remain open.
**Professor/source reference:** [authoritative audit, requirement 25](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** Batch 2 focused role/navigation suite: 10 files, 85 tests passed; see [Batch 2 report](G_SUB_47_BATCH_2_WORKSPACE_IMPLEMENTATION_REPORT.md) for exact command and limitations.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Batch 2 — selected-workspace/navigation review.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 2 update:** Existing role-owned return and sidebar integration tests ran; real-browser focus and every role dirty-state scenario remain unverified.


**Batch 28 update:** In Progress → Tested. Existing role-owned callbacks were retained; Formatter notification navigation now protects unsaved notes/comments. Five-role synthetic Chromium verified A/B/A return, dirty cancellation/confirmation and list focus, EIC filter preservation, and Author pending-save switching; focused navigation tests passed. See [Batch 28 report](G_SUB_47_BATCH_28_WORKSPACE_PROGRESS_COMPLETION_REPORT.md).

### 26. Color scheme — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `index.css` already defines semantic tokens; role and dashboard CSS contain hard-coded blues, gray borders and state colors; `RoleSelection.css` uses navy/gold role accents. Computed contrast not measured.
- **FE:** extend existing tokens for surface, text, borders, action, focus and status; apply consistently across `index.css`, `App.css`, `SharedSidebar.css`, dashboard CSS, `ManuscriptProgress.css` and shared panels. **BE/data:** none. **Security/deps:** labels and focus must remain visible; 7–9/40/47. **Tests:** computed contrast, focus/hover/disabled states and desktop screenshots.

**Tracker status:** In Progress.

**Batch 20 update:** Semantic tokens were extended and applied to the sidebar, notification bell and selected shared surfaces. Desktop computed contrast samples passed, but all dashboard colors and states have not been audited.
**Professor/source reference:** [authoritative audit, requirement 26](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 27. Role presentation — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** chooser has EIC, Editor, Reviewer, Author; formatter accounts use Editor choice (3). Initial and final editors are editor assignments (`InitialEditorInvitation`, `FinalEditorInvitation`), not independent stored role values; registration creates authors (`app/routers/users.py`).
- **FE:** clarify responsibilities within workspace/invitation context while keeping the four-card chooser and `General / Copy Editor` label. **BE/data:** no change for clearer labels. A true additional account role or multi-role model needs separately approved auth/schema design. **Security/deps:** never turn frontend role selection into privileges or create Formatter card; 1–3/37–38. **Tests:** all five stored-role routing paths, mismatched selection and assignment access.

**Tracker status:** In Progress.

**Batch 20 update:** Four chooser cards now explain responsibilities and the sidebar provides role-specific context, including Formatter under General / Copy Editor. Full role-routing and invitation-context acceptance remains open.
**Professor/source reference:** [authoritative audit, requirement 27](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 28. EIC manuscript listing — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `EICDashboard.jsx:112–124` filters loaded `/manuscripts/` by title/ID and status; status options sorted. `app/routers/manuscripts.py:get_all_manuscripts` also accepts optional status. No manuscript sort control, pagination or list summary in this component.
- **FE:** add deterministic sorting, counts, pagination, status groupings and accessible result/error states; preserve existing search/filter. **BE/data:** none initially for bounded client data; optional EIC-authorized paginated search endpoint/DTO if measured scale demands, no inherent migration. **Security/deps:** list only accessible non-drafts; 29/33. **Tests:** EIC navigation, filters, sorting ties, page clamping, unknown statuses and draft privacy (`tests/test_eic_dashboard.py`).

**Tracker status:** In Progress.

**Batch 20 update:** Search/filter/sort and counts were retained; clear-search and 10/25/50-row pagination were added. Created date is the only available date in the list; authoritative submission/updated dates and per-EIC ownership are not provided. Status returned to In Progress pending the new acceptance conditions.
**Professor/source reference:** [authoritative audit, requirement 28](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 11 update:** EIC list uses the existing authorized dataset, exact-status counts, deterministic sorting, search/filter and ten-item client pages. Focused frontend, isolated authorization and synthetic desktop browser tests passed. No user acceptance or large-scale performance claim. See [Batch 11 report](G_SUB_47_BATCH_11_EIC_MANUSCRIPT_LIST_IMPLEMENTATION_REPORT.md).

### 29. EIC middle box and alerts — Needs clarification

**Original audit wording and evidence (verbatim):**

- **Evidence:** `EICDashboard.jsx:122–125` and `EICDashboard.css:.eic-grid` render list plus `<main>`; unselected main says “Select a manuscript…” and becomes functional detail after selection. This is the likely empty box, not visually confirmed. `NotificationBell.jsx` displays actual user notifications.
- **FE:** replace unselected placeholder with a useful EIC queue of actionable-looking but conservatively labeled status groups and unread alerts; click opens selected manuscript or notifications. **BE/data:** derive safe queue from authorized list; accurate decision-readiness across manuscripts requires an EIC aggregate endpoint grounded in `review_progress` and invitation/submission records. No inherent migration for read-only aggregation. **Security/deps:** do not infer ready-to-decide from status or leak unrelated records inside detail; 23/28/31/32/40. **Tests:** queue classification, alert navigation, empty/error and hidden drafts.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 29](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 12 update:** The unselected EIC workspace now shows conservative workflow groups from the existing authorized, deduplicated list and a user-specific unread summary linked to the shared notification bell. Focused frontend tests and a synthetic desktop browser run passed. Review eligibility is not available in the list response, so decision-ready/action-required counts are deliberately not asserted; comprehensive eligibility and authorization coverage remain outstanding. Status remains In Progress. See [Batch 12 report](G_SUB_47_BATCH_12_EIC_WORK_QUEUE_IMPLEMENTATION_REPORT.md).

### 30. Fewer visual boxes — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** EIC overview, action cards, reviewer management, formatting and history are separate sections (`EICDashboard.jsx`); progress has nested header/summary/details. Editor has multiple stats and context cards.
- **FE:** merge duplicate containers and group secondary sections into disclosures while preserving actions, errors and hierarchy. `EICDashboard.jsx/.css`, `EditorDashboard.jsx/.css`, `ManuscriptProgress.jsx/.css`, other role CSS. **BE/data:** none. **Security/deps:** visibility is not permission; 12/21/34/35. **Tests:** role action reachability, disclosure and desktop layout.

**Tracker status:** In Progress.

**Batch 20 update:** The selected EIC overview no longer adds a redundant boundary inside its workspace; earlier visual simplification is preserved. Comprehensive five-role nested-box and action verification is not complete.
**Professor/source reference:** [authoritative audit, requirement 30](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** Batch 3 focused role/workspace suite: 7 files and 64 tests passed; exact command and limitations are in the [Batch 3 report](G_SUB_47_BATCH_3_DASHBOARD_LAYOUT_IMPLEMENTATION_REPORT.md).
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Batch 2 — selected-workspace/navigation review.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 3 update:** Scoped selected-workspace CSS removes nested borders from Author/EIC notes and EIC staff comments. Existing workflow actions and role panels remain; desktop/mobile visual and contrast review was not performed.

**Batch 13 update:** Embedded editing panels and EIC history rows use fewer nested borders; selected Editor statistics are more compact, and staff comments/notes retain separate disclosures. Ten focused frontend suites passed and five synthetic desktop screenshots were captured. Status remains In Progress pending comprehensive real workflow and Formatter verification and user acceptance. See [Batch 13 report](G_SUB_47_BATCH_13_VISUAL_SIMPLIFICATION_IMPLEMENTATION_REPORT.md).

### 31. Participant prompts — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `ManuscriptProgress.jsx` renders API `next_action`; `PROGRESS_STATUS_MAP` in `app/routers/manuscripts.py` is status-based and often generic (“Check ... workflow”), not necessarily personalized. Role panels contain contextual controls and some instructions.
- **FE:** display one clear task or waiting message per assigned participant in selected stage, with relevant permitted action link. **BE/data:** extend a read-only role/assignment-aware task projection using invitation and stage evidence; no inherent migration. **Security/deps:** not a permission grant, never reveal hidden identity; distinguish pending, declined, stale and no action; 20/32/33. **Tests:** every role, stage and declined/revision branch; unauthorized users get no prompt with private details.

**Tracker status:** In Progress.

**Batch 21 update:** Existing role-aware frontend guidance was reused; withdrawn EIC guidance now has an explicit no-action message. A new authenticated backend task projection and exhaustive role/stale scenarios remain open.
**Professor/source reference:** [authoritative audit, requirement 31](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 4 update:** Batch 4 adds reviewer assignment/invitation and availability guidance in frontend/src/participantPrompts.js and ReviewerDashboard.jsx, using existing assignment and progress responses; other roles retain generic existing progress guidance and require participant-specific work. No API or authorization changed. Focused 10-file suite: 122 tests passed. No browser verification. See [Batch 4 report](G_SUB_47_BATCH_4_PARTICIPANT_PROMPTS_IMPLEMENTATION_REPORT.md) for commands and limitations.

**Batch 5 update:** Batch 5 adds Author status guidance and assignment-scoped Initial Editor, Final Editor and Formatter guidance through participantPrompts.js and existing panels. Unit and selected integration tests passed; role-wide browser, stale-request and authorization integration remain unverified, and multiple stage panels may still show multiple contextual prompts. See [Batch 5 report](G_SUB_47_BATCH_5_PARTICIPANT_PROMPTS_COMPLETION_REPORT.md) for exact tests and limits.

**Batch 6 update:** Batch 6 labels embedded initial/final editing and formatting messages as stage guidance and preserves the primary workspace prompt. Synthetic Author A/B switching and sidebar keyboard activation were exercised in a real headless browser; seven-role integration and all stale/error scenarios remain unverified. See [Batch 6 report](G_SUB_47_BATCH_6_PROMPT_INTEGRATION_VERIFICATION_REPORT.md).

**Batch 7 update:** Batch 7 makes guidance for reviewer and editor/formatter invitation actions explicitly unconfirmed when current assignment/round eligibility is not supplied; Author and Reviewer synthetic browser A/B checks ran. Other role browser scenarios, authorization integration, and coordinated primary prompts remain unverified. See [Batch 7 report](G_SUB_47_BATCH_7_FINAL_PROMPT_COORDINATION_REPORT.md).

### 32. EIC next-action prompt — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** shared next action is generic; `EICDashboard.jsx` computes `canDecide`, approval and other stage-specific controls plus fallback messages at :448.
- **FE:** position EIC-specific task/waiting reason near selected stage header, linking to existing action, with no duplicated conflicting message. **BE/data:** reuse `/eic/manuscripts/{id}/overview` and server-side `review_progress`; consider additive `tasks` field. No schema change. **Security/deps:** no action if eligibility unknown; 29/31/33. **Tests:** scan, invited editor, incomplete reviews, ready decision, author agreement and error/stale status.

**Tracker status:** In Progress.

**Batch 21 update:** The current-stage prompt can now navigate to the existing EIC Decision view only when server can_decide and a valid round agree. Missing round and stale conditions fail closed. Full scenario and role-level coverage remains open.
**Professor/source reference:** [authoritative audit, requirement 32](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 4 update:** Batch 4 uses existing /eic/manuscripts/{id}/overview and review_progress in participantPrompts.js and EICDashboard.jsx for screening, invitation, review eligibility, and waiting guidance; EIC refresh failure now disables actions pending refresh. Several workflow scenarios remain generic or lack integrated coverage. Focused 10-file suite: 122 tests passed. No browser verification. See [Batch 4 report](G_SUB_47_BATCH_4_PARTICIPANT_PROMPTS_IMPLEMENTATION_REPORT.md) for commands and limitations.

**Batch 5 update:** Batch 5 uses existing final_invitations and final_workflow_submissions to distinguish final-editor waiting and EIC/author review. The EIC overview lacks formatting assignment details; guidance remains non-specific and requirement remains In Progress. See [Batch 5 report](G_SUB_47_BATCH_5_PARTICIPANT_PROMPTS_COMPLETION_REPORT.md) for exact tests and limits.

**Batch 6 update:** Batch 6 reads existing EIC-authorized /formatting/manuscripts/{id}, checks selected ID and refresh version, and displays evidence-based formatting guidance; stale A/B response regression passed. EIC browser coverage and full eligibility/authorization integration remain unverified. See [Batch 6 report](G_SUB_47_BATCH_6_PROMPT_INTEGRATION_VERIFICATION_REPORT.md).

**Batch 7 update:** Batch 7 requires a valid review round and server can_decide before showing decision navigation; status-only screening/editing/formatting messages no longer present an action link. EIC role browser and full server eligibility coverage remain unverified. See [Batch 7 report](G_SUB_47_BATCH_7_FINAL_PROMPT_COORDINATION_REPORT.md).

### 33. Open at current EIC stage and navigate stages — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `EICDashboard.jsx:open` fetches overview; `ManuscriptProgress` displays current stage, but one long detail screen contains conditional action cards rather than a current-stage route. Progress status map represents nine stages. Back/forward navigation is not implemented as stage pages.
- **FE:** open a manuscript on a current-stage view, allow read-only navigation to other stages with clear current-stage marker, disabled/unavailable states, and guarded dirty navigation. **BE/data:** reuse `/progress` and `/eic/manuscripts/{id}/overview`; no backend change to browse. Stage transitions remain existing guarded actions, never merely previous/next clicks. **Security/deps:** explicit authorized transition endpoints for actual movement if separately specified; 20/31/32/35/36. **Tests:** current-stage resolution, past/future, rejection/revision/legacy, unsaved input, direct links and forbidden transitions.

**Tracker status:** In Progress.

**Batch 21 update:** The selected stage follows a confirmed current-stage advance when the user was viewing the prior current stage; manually browsed stages remain selected. Chromium browsed all nine stages without writes and switched A to B; comprehensive legacy and stale browser coverage remains open.
**Professor/source reference:** [authoritative audit, requirement 33](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 8 update:** Batch 8 adds local nine-stage selector initialized from the existing progress API; stage selection is presentation-only and dirty changes are guarded. Synthetic EIC browser checked current/earlier/future stages and A/B switching; stale/legacy and role authorization coverage is incomplete. See [Batch 8 report](G_SUB_47_BATCH_8_EIC_STAGE_NAVIGATION_IMPLEMENTATION_REPORT.md).

**Batch 9 update:** Batch 9 retains local stage navigation; synthetic EIC browser visited all nine history regions, tested keyboard, dirty cancellation and A/B selection. Complete legacy/stale and role authorization coverage remains incomplete. See [Batch 9 report](G_SUB_47_BATCH_9_EIC_STAGE_HISTORY_IMPLEMENTATION_REPORT.md).

### 34. Separate Comments and Activity History — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `EICDashboard.jsx:449` has “Comments and Activity History” mixing scan/decision comments and events; `EditorDashboard.jsx:766` uses same heading; staff General Comments is separate.
- **FE:** show distinct comments and activity/history sections with role-specific labels and appropriate ordering; don't duplicate sensitive review comments. **BE/data:** existing overview and staff comment endpoints; a chronological role-filtered timeline endpoint is optional (14). **Security/deps:** private notes, staff comments and reviewer feedback have different audiences; 13/14/42. **Tests:** `test_general_comments.py`, review visibility and no cross-role leaks.

**Tracker status:** Tested.

**Batch 21 update:** Batch 21 regression: EICActivityHistory frontend tests and isolated test_general_comments.py passed within the documented suites; existing audience restrictions and separate history remain.
**Professor/source reference:** [authoritative audit, requirement 34](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** Batch 2 focused role/navigation suite: 10 files, 85 tests passed; see [Batch 2 report](G_SUB_47_BATCH_2_WORKSPACE_IMPLEMENTATION_REPORT.md) for exact command and limitations.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Batch 2 — selected-workspace/navigation review.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 2 update:** Editor review-submission activity is now ordered by actual timestamps, with undated records last; tests verify history excludes review comments. EIC separates workflow comments and activity history. Browser review remains open.

**Batch 14 update:** EIC activity is ordered by available recorded timestamps with deterministic ties and undated records last; reviewer feedback has a separate disclosure from workflow comments and activity. Existing initial/final editing download controls remain. Focused tests, a migration-free synthetic staff authorization check, reviewer projections, and EIC/Editor desktop browser sessions passed. Formatting/publication and historical events absent from the overview are not represented in the combined timeline; broader end-to-end and user acceptance remain outstanding. See [Batch 14 report](G_SUB_47_BATCH_14_COMMENTS_ACTIVITY_HISTORY_IMPLEMENTATION_REPORT.md).

### 35. Individual EIC stage pages — Missing

**Original audit wording and evidence (verbatim):**

- **Evidence:** current `EICDashboard.jsx` conditionally renders multiple workflow sections in one selected detail component; no independent stage router/pages inspected.
- **FE:** extract stage-specific views/components and controlled stage selection with shared manuscript shell; routes or local state are implementation choices, not assumed required. `EICDashboard.jsx/.css`, `ManuscriptProgress.jsx`, stage panels, `App.jsx` only if needed. **BE/data:** existing overview/progress/action endpoints initially; additive stage DTOs only when needed. No schema change for presentation. **Security/deps:** future-stage browsing must not confer access or change status; 23/25/31–34. **Tests:** each stage deep link/selection, direct refresh if routed, dirty guards and unchanged workflow actions.

**Tracker status:** In Progress.

**Batch 21 update:** Seven screening, initial-editing, peer-review, decision and final-editing action cards were extracted as focused components using the existing handlers. Read-only history remains centralized in EICStageHistory and not all nine stages have independent components; work remains in progress.
**Professor/source reference:** [authoritative audit, requirement 35](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 8 update:** Batch 8 groups existing EIC action panels by selected stage and provides stage titles and available summaries. Several historical/future stage details remain sparse and reviewer/formatting panels remain mounted but hidden to preserve forms; full nine-stage and real-API verification remains incomplete. See [Batch 8 report](G_SUB_47_BATCH_8_EIC_STAGE_NAVIGATION_IMPLEMENTATION_REPORT.md).

**Batch 9 update:** Batch 9 adds source-backed stage history, review-round groupings without reviewer names/comments, agreement record and confirmed publication link. Missing backend historical fields, previous publication versions and full authorization/browser scenario coverage remain. See [Batch 9 report](G_SUB_47_BATCH_9_EIC_STAGE_HISTORY_IMPLEMENTATION_REPORT.md).

### 36. EIC stage bypass — Missing as a general feature; semantics unspecified

**Original audit wording and evidence (verbatim):**

- **Evidence:** existing EIC action endpoints and `final_workflow.py`, `formatting.py` check specific statuses and required agreement/invitations. No universal skip endpoint/policy is evident. Some steps are security or evidence prerequisites.
- **FE:** display only explicitly permitted, explained bypass actions with reason, confirmation and consequence. **BE/data:** design per-stage allowlist, authorized state transitions, reasoned immutable audit and idempotency; likely additive bypass event model/migration and new EIC-only endpoint(s). This is a breaking workflow/authorization change requiring separate approval, not a generic status update. **Security/deps:** never bypass ownership, anonymity, file integrity, agreement or review safeguards without explicit approved policy; 33/35/37–43. **Tests:** allowed/denied paths, atomicity, concurrency, history, legacy and attempts by non-EIC.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 36](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 15 investigation:** Source review identifies distinct prospective and legacy paths and recommends an empty bypass allowlist until the professor approves specific operations and evidence requirements. No bypass, migration or workflow change was implemented. See [Batch 15 audit](G_SUB_47_BATCH_15_STAGE_BYPASS_POLICY_AUDIT.md).

### 37. Editor invitation metadata — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `app/routers/eic.py:my_initial_editing` returns title, status, invitation and only exposes editing submissions after acceptance. `app/models.py:Manuscript` stores title, abstract, author ID, status, date and current file path, not subject, keywords, table count or sample. AI analysis includes a word count for supported processed text, but not an authoritative universal count.
- **FE:** invitation summary presents approved title/subject/keywords/counts and a safe excerpt only when available, with explicit unavailable/provenance labels; `InitialEditingPanel.jsx` and `FinalEditingPanel.jsx`. **BE/data:** add a minimal invitation-specific DTO; collect subject/keywords via additive schema if required, and use bounded verified extraction or author-supplied figures with source labels. Existing preview of a pending invitation intentionally excludes history. **Security/deps:** separately decide what may be shared before acceptance, protect blind identities and never expose raw file/path; 17/38/41. **Tests:** pending vs accepted, pre-invitation denial, absent counts and unsupported formats, blind-safe sample.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 37](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 16 update:** Initial and Final Editor invitation summaries now identify the invitation title/status and explicitly label unavailable preview metadata. Pending or declined editor invitations do not render returned editing submissions. Focused synthetic frontend tests and an Editor browser session passed; verified extraction, approved preview scope and full authorization remain open. See [Batch 16 report](G_SUB_47_BATCH_16_DOCUMENT_LIFECYCLE_IMPLEMENTATION_REPORT.md).

**Batch 17 update:** Initial and Final Editor invitation APIs now include the author-provided abstract for the accepted invited editor only; pending, declined and other users receive no abstract. Isolated HTTP and frontend tests passed. Other metadata/extraction remains unavailable. See [Batch 17 report](G_SUB_47_BATCH_17_DOCUMENT_DISTRIBUTION_CORE_IMPLEMENTATION_REPORT.md).

**Batch 17B update:** No new metadata extraction was implemented in Batch 17B; accepted-editor abstract behavior remains as previously recorded. See [Batch 17B report](G_SUB_47_BATCH_17B_DISTRIBUTION_CORE_COMPLETION_REPORT.md).

**Batch 17C update:** Accepted-editor author-provided abstract remains; no additional verified subject, count or document extraction was implemented. See [Batch 17C report](G_SUB_47_BATCH_17C_DISTRIBUTION_WORKFLOW_COMPLETION_REPORT.md).

**Batch 22 update:** Invitation summaries now show recorded invitation and response times, stage and editor, labeling missing values and legacy timezone uncertainty. Initial invitation acceptance uses conditional transaction updates. Isolated tests and the synthetic initial-editor desktop flow passed; final-editor browser and approved preview metadata remain unverified. See [Batch 22 report](G_SUB_47_BATCH_22_INVITATION_DISTRIBUTION_HISTORY_REPORT.md).

**Batch 23 update:** A synthetic final-editor invitation was created through the API and its metadata and acceptance were checked in a real desktop browser. Other approved preview fields remain unavailable. See [Batch 23 report](G_SUB_47_BATCH_23_DOCUMENT_LIFECYCLE_COMPLETION_REPORT.md).

### 38. All participants agree to policy — Missing as a general acceptance mechanism

**Original audit wording and evidence (verbatim):**

- **Evidence:** editor/reviewer/formatter invitations accept/decline; `AuthorAgreement` is a distinct post-acceptance author agreement, not a participant policy. Invitation request schemas (`app/schemas.py`, `assignments.py`, `final_workflow.py`, `formatting.py`) do not establish a universal policy acceptance record.
- **FE:** show versioned policy at each applicable invitation/participation acceptance, accessible before confirming. **BE/data:** define policy version/text, actor, assignment, timestamp and acceptance evidence; add transactional, immutable acceptance records and a migration if approved; update invitation endpoints atomically. Define author participation trigger and legacy handling. **Security/deps:** prevent forged actor/version, double acceptance, privilege expansion or misrepresenting old records; 36/39/41/43. **Tests:** each role, decline, missing/stale version, retries, concurrent acceptance, authorization, backward compatibility.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 38](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 39. Notify EIC when editor accepts; EIC sends documents — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `app/routers/eic.py:respond_initial_editor_invitation` creates `initial_editor_response` notification for inviting EIC; `app/routers/final_workflow.py:respond` does likewise for final editing. Invitation acceptance and existing authorized file access do not create an explicit EIC document-send transaction.
- **FE:** show response notification and an EIC action to grant/send the exact permitted artifact after acceptance. **BE/data:** reuse notification for acceptance; a manual distribution endpoint and persistent artifact/recipient/grant event may be needed; do not treat a notification or existing access as proof of transfer. **Security/deps:** accepted assignment, current version, actor, blind policy and idempotency; 38/41/45. **Tests:** recipient ownership, duplicate accept/send, failed notification/commit, actual access before/after chosen policy.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 39](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 16 update:** Existing initial and final acceptance notifications were inspected and preserved. The stage view now distinguishes invitation responses from unrecorded distribution; no manual grant/send operation or delivery claim exists. Durable recipient/version-bound distribution remains blocked. See [Batch 16 report](G_SUB_47_BATCH_16_DOCUMENT_LIFECYCLE_IMPLEMENTATION_REPORT.md).

**Batch 17 update:** No manual distribution operation or delivery status was implemented; existing acceptance notifications remain. The requested core remains open. See [Batch 17 report](G_SUB_47_BATCH_17_DOCUMENT_DISTRIBUTION_CORE_IMPLEMENTATION_REPORT.md).

**Batch 17B update:** An incomplete additive schema candidate was tested in isolated databases; no manual distribution endpoint, access-grant retrieval or EIC control was implemented. See [Batch 17B report](G_SUB_47_BATCH_17B_DISTRIBUTION_CORE_COMPLETION_REPORT.md).

**Batch 17C update:** A manual current-manuscript snapshot can be granted to an accepted Initial or Final Editor, who can download it; revocation denies future downloads. Synthetic HTTP and real-backend browser flows passed. Broader artifacts and acceptance remain open. See [Batch 17C report](G_SUB_47_BATCH_17C_DISTRIBUTION_WORKFLOW_COMPLETION_REPORT.md).

**Batch 22 update:** Initial acceptance, EIC notification, manual grant, recipient download and revocation were exercised through isolated HTTP and a real synthetic desktop browser; duplicate and simultaneous initial responses and notification failure were tested. Final-editor end-to-end notification/distribution browser evidence remains outstanding. See [Batch 22 report](G_SUB_47_BATCH_22_INVITATION_DISTRIBUTION_HISTORY_REPORT.md).

**Batch 23 update:** The final-editor acceptance, EIC notification, existing current-manuscript manual grant, exact editor download and revocation were exercised in synthetic HTTP and desktop browser flows. Arbitrary final-editing artifact selection remains unsupported. See [Batch 23 report](G_SUB_47_BATCH_23_DOCUMENT_LIFECYCLE_COMPLETION_REPORT.md).

### 40. More visible bell — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** shared `NotificationBell.jsx` uses a 20px emoji, unread badge and popover; `NotificationBell.css` styles it; role headers include it. Sidebar can open the bell via `App.jsx`.
- **FE:** larger clear icon/button, contrast, focus and visible unread count in desktop headers. **BE/data:** none. **Security/deps:** retain user-specific `/notifications/my` and unread/read behavior, no auto-mark on navigation; 23/29/47. **Tests:** `NotificationBell.test.jsx`, `App.sidebar.test.jsx`, accessible name, count, keyboard and contrast.

**Tracker status:** Tested.

**Batch 20 update:** The existing SVG bell now opens immediately, reports loading/error without a stale count, describes zero unread accessibly, and closes on Escape with focus returned. Focused tests and synthetic desktop EIC interaction passed.
**Professor/source reference:** [authoritative audit, requirement 40](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 10 update:** Shared SVG bell, high-contrast inline count, keyboard/focus styling and token-scoped async response guard implemented. Focused frontend and isolated ownership tests passed; synthetic 1440×900 Chromium checked five roles and Author notification navigation. No user acceptance claimed. See [Batch 10 report](G_SUB_47_BATCH_10_NOTIFICATION_BELL_IMPLEMENTATION_REPORT.md).

### 41. Automatic versus manual document distribution — Missing as an explicit choice

**Original audit wording and evidence (verbatim):**

- **Evidence:** accepted invitations and assignment-bound download access exist; `ReviewRoundFile` / `ReviewAssignmentFile` bind a round file. `Notification`, `NotificationEvent`, `EmailOutbox` and `EmailDeliveryAttempt` describe notifications/email, not proof that a particular manuscript file was distributed. No EIC auto/manual distribution control or delivery ledger was found.
- **FE:** EIC selects mode per defined scope and sees pending/sent/failed status plus retry; participants see only authorized available documents. **BE/data:** approved additive mode and immutable distribution/grant ledger bound to manuscript, exact artifact/version, recipient, assignment, round, actor, mode, timestamps and idempotency key; transactional outbox/worker if external transport is used. New EIC API, recipient authorization and integration with acceptance are required. No actual email attachment is implied; distinguish access granted, notification enqueued, sent and acknowledged/downloaded. **Security/deps:** blind-review sanitized artifact, revoked invitations, race/retry, no credential leak, manual default for existing records; 38/39/44–46. **Tests:** exactly-once logical grant under retries/concurrency, failure recovery, no early access, recipient/version binding, migration and no network in isolated tests.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 41](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 16 update:** No manual or automatic distribution mode, durable grant or outbox integration was implemented; safe distribution requires approved scope, additive persistence and separately authorized migration. Existing access grants remain unchanged. See [Batch 16 report](G_SUB_47_BATCH_16_DOCUMENT_LIFECYCLE_IMPLEMENTATION_REPORT.md).

**Batch 17 update:** No distribution mode or durable ledger was implemented and automatic distribution remains unavailable. Manual grants and associated transactional tests remain open. See [Batch 17 report](G_SUB_47_BATCH_17_DOCUMENT_DISTRIBUTION_CORE_IMPLEMENTATION_REPORT.md).

**Batch 17B update:** Migration 021 contains a manual-only candidate ledger and reservations; it is not deployment-ready and no automatic mode or distribution service exists. See [Batch 17B report](G_SUB_47_BATCH_17B_DISTRIBUTION_CORE_COMPLETION_REPORT.md).

**Batch 17C update:** Migration 021 and a manual-only grant service were exercised in isolated databases; notification creation is recorded separately and email is not requested. Automatic distribution remains disabled; storage recovery and broad authorization testing need follow-up. See [Batch 17C report](G_SUB_47_BATCH_17C_DISTRIBUTION_WORKFLOW_COMPLETION_REPORT.md).

**Batch 22 update:** Existing manual grants remain the only enabled mode; selection is assignment-identity bound and retries cannot report a revoked grant as active. Automatic trigger, scope and recipient policy are unresolved, so no automatic configuration is persisted or enabled. See [Batch 22 report](G_SUB_47_BATCH_22_INVITATION_DISTRIBUTION_HISTORY_REPORT.md).

**Batch 23 update:** Existing manual grants were regression-tested. No automatic trigger, scope or artifact release policy is approved; automatic execution and configuration remain unavailable. No grant or workflow semantics were changed. See [Batch 23 report](G_SUB_47_BATCH_23_DOCUMENT_LIFECYCLE_COMPLETION_REPORT.md).

### 42. Stage-specific dialogue — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `GeneralComment` is staff-only with fixed `visibility='staff'`; `PersonalNote` is private per user/manuscript; review and stage approval comments exist in individual records. None is a universal stage-thread audience system.
- **FE:** separate private notes, staff conversation and stage threads; show appropriate participants and audience before sending. **BE/data:** design additive stage/round-scoped message/thread and recipient visibility model plus GET/POST endpoints if broader dialogue is required; migrate nothing into broader visibility by default. **Security/deps:** author/reviewer communication, anonymity and participant assignment require explicit per-message policy; no blanket expansion of general comments. Related 13/34/38/45. **Tests:** audience matrix, hidden identities, historical assignments, replay and cross-manuscript denial.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 42](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 43. Auto-generate Author Agreement — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `app/routers/eic.py:make_eic_decision` creates `AuthorAgreement` for an accept decision; `app/agreement_content.py` supplies `placeholder-v1` text explicitly not a legal agreement. `app/routers/agreements.py` reads and accepts/declines the stored version; `AuthorAgreementPanel.jsx` presents it. `final_workflow.py:invite` requires acceptance.
- **FE:** show approved immutable agreement version and user response; existing panel is foundation. **BE/data:** use an approved versioned template and optionally generate an immutable artifact tied to the decision/author; existing text/version/timestamps already support simple snapshot, new artifact metadata only if a downloadable document is required. **Security/deps:** no invented legal terms; duplicate decision/retry, owner-only response, preserve old version; 38/44. **Tests:** `tests/test_author_agreement.py`, `test_final_workflow.py`, author agreement panel sync; idempotence and original content preservation.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 43](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 44. Reviewer generations and received/reviewed documents — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `Manuscript.review_round`, `ReviewAssignment.review_round`, `ReviewRoundFile`, `ReviewAssignmentFile` and `app/review_files.py` support arbitrarily numbered rounds and assignment-specific input. `Review` and `ReviewCreate` store comments/recommendation, not a reviewed manuscript file. `ReviewerDashboard.jsx` shows round/assignment; `EditorDashboard.jsx` groups review history by round.
- **FE:** display generation/round dynamically, assignment-specific input and submitted review separately; if file absent label “review comments” and unavailable. **BE/data:** an uploaded reviewed document requires safe new assignment-bound upload, immutable artifact and authorized download records/endpoints; a read model must join by round and avoid rewriting old bindings. **Security/deps:** avoid disclosing reviewer identity or unredacted documents to author; acceptance, version integrity, multiple reviewers and experimental blind policies; 15/41/45/46. **Tests:** rounds 1–3+, two reviewers, late submissions, wrong assignment, unsupported formats, authorization and original-file preservation (`test_reviewer_download.py`, `test_role_safe_progress.py`, `test_blind_review_visibility.py`).

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 44](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 16 update:** Reviewer workspace now labels its assignment round, incoming availability and unavailable reviewed-document attachment separately from review comments. Synthetic round 1, 2, 3 and 12 tests and reviewer browser coverage passed; reviewed-file upload and comprehensive lifecycle checks remain open. See [Batch 16 report](G_SUB_47_BATCH_16_DOCUMENT_LIFECYCLE_IMPLEMENTATION_REPORT.md).

**Batch 17 update:** No reviewed-document upload, versioned storage or editorial download was implemented; existing assignment-specific reviewer release remains unchanged. See [Batch 17 report](G_SUB_47_BATCH_17_DOCUMENT_DISTRIBUTION_CORE_IMPLEMENTATION_REPORT.md).

**Batch 17B update:** No reviewer document upload, secure retrieval or EIC release was implemented; the candidate schema is not an upload workflow. See [Batch 17B report](G_SUB_47_BATCH_17B_DISTRIBUTION_CORE_COMPLETION_REPORT.md).

**Batch 17C update:** An active accepted reviewer can upload a versioned reviewed file for the current assignment and round; EIC-only download was tested. Broader round, privacy, concurrency and lifecycle coverage remains open. See [Batch 17C report](G_SUB_47_BATCH_17C_DISTRIBUTION_WORKFLOW_COMPLETION_REPORT.md).

### 45. EIC full generation document record — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `/eic/manuscripts/{id}/overview` returns scans, initial editing submissions/confirmations, assignments/reviews/decisions, final editing and agreement; `/manuscripts/{id}/versions` covers manuscript uploads. `ReviewRoundFile` and `ReviewAssignmentFile` bind review inputs; stage artifact models are separate. There is no single complete transfer ledger; a round binding is not a delivery receipt, and review submission has no file.
- **FE:** timeline grouped by round/generation and artifact direction with explicit unavailable/unknown and authorized download actions. **BE/data:** EIC-only read projection joining authoritative version and stage records; prospectively record missing transfer/distribution events and reviewer artifacts (41/44) in additive schema only when approved. Preserve legacy ambiguity; never fabricate sequence or sender. **Security/deps:** role checks, verified path/digest and version association, blind policies; 14/39/41/44/46. **Tests:** distinct inbound/outbound per round, multiple reviewers, legacy missing bindings, idempotent sends and access denial.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 45](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

**Batch 16 update:** Existing EIC Initial Editing, Peer Review and Final Editing stage history now explicitly distinguishes invitation/review records from unknown distribution and binding evidence. Synthetic stage history tests and browser screenshot were run; a unified artifact/version and delivery ledger remains unavailable. See [Batch 16 report](G_SUB_47_BATCH_16_DOCUMENT_LIFECYCLE_IMPLEMENTATION_REPORT.md).

**Batch 17 update:** The EIC overview now projects matching manuscript-and-round assignment bindings without paths; stage history labels integrity unverified and delivery unknown. This is not a full artifact or distribution ledger. See [Batch 17 report](G_SUB_47_BATCH_17_DOCUMENT_DISTRIBUTION_CORE_IMPLEMENTATION_REPORT.md).

**Batch 17B update:** No new generation history projection was implemented; the candidate ledger is not integrated and contains no historical backfill. See [Batch 17B report](G_SUB_47_BATCH_17B_DISTRIBUTION_CORE_COMPLETION_REPORT.md).

**Batch 17C update:** EIC can see new outgoing grant and incoming reviewed-document records, but a complete history of all legacy and stage artifacts remains unavailable. See [Batch 17C report](G_SUB_47_BATCH_17C_DISTRIBUTION_WORKFLOW_COMPLETION_REPORT.md).

**Batch 22 update:** The EIC distribution section now includes source-backed initial, peer-review binding, final and available formatting records, plus reviewed-artifact digests; legacy transfer and version evidence remains explicitly unknown. It is not a complete historical ledger. See [Batch 22 report](G_SUB_47_BATCH_22_INVITATION_DISTRIBUTION_HISTORY_REPORT.md).

**Batch 23 update:** The EIC history now lists and searches the existing authorized manuscript file-version API, with authenticated downloads and stale-response protection; file presence is not represented as submission or delivery. Full artifact/round history and metadata remain incomplete. See [Batch 23 report](G_SUB_47_BATCH_23_DOCUMENT_LIFECYCLE_COMPLETION_REPORT.md).

### 46. Author generation document history — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** authors can use manuscript versions endpoint and stage-specific edited/formatting workflows; `AuthorDashboard.jsx` and panels show current information, not a unified generation transfer record. The EIC overview is EIC-only and contains reviewer names/comments.
- **FE:** author-specific generation/history view of authorized submissions and released outputs, with truthful unavailable labels. **BE/data:** a separate owner-authorized filtered projection; do not reuse EIC DTO wholesale; prospectively record missing transfer/release events. New reviewed files require explicit editorial release policy and sanitized versions. **Security/deps:** preserve reviewer anonymity, editor-private comments, author ownership, version integrity; 41/44/45. **Tests:** two authors, multiple rounds, unapproved review files, blind mode, old records and version downloads.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 46](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** High.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

### 47. Colors, presentation and original branding — Partial

**Original audit wording and evidence (verbatim):**

- **Evidence:** `branding.js`, `RoleSelection.css` and existing semantic tokens provide navy/gold and role colors; dashboard CSS uses independent hard-coded palettes. Original design reference is not identified or verified in this audit.
- **FE:** reuse the current identity and harmonize cards, typography, state colors, focus and buttons through `index.css` and shared/role CSS; compare against the actual original reference when provided. **BE/data:** none. **Security/deps:** high-contrast action, notification and status labels; 26/40. **Tests:** desktop role screenshots, accessible contrast and keyboard focus. Do not assume an unseen original design.

**Tracker status:** In Progress.
**Professor/source reference:** [authoritative audit, requirement 47](G_SUB_Complete_Requirements_Audit_1-47.md); see its source evidence above. The four-card reference image is not acceptance evidence for this item.
**Frontend and backend/models:** Exact files, components, routes, services and models identified in the source audit are preserved in the evidence and FE/BE/data text above; where the audit names no specific file or endpoint, it is not yet established and must be identified during the assigned batch.
**Existing tests:** The exact test names, where identified, are preserved in the original Tests text above; a named test has not necessarily been executed in this task.
**Tests executed in this task:** No requirement-specific execution is claimed; the Batch 1 role-dashboard suite may overlap this item.
**Screenshot/browser evidence:** Original reference image inspected as described above; no current application browser screenshot or visual acceptance was obtained.
**Remaining implementation:** Follow the FE and BE/data work in the verbatim entry above, after verifying the current source; do not rewrite functionality already meeting the requirement.
**Security and dependencies:** The original Security/deps text above applies; preserve role authorization, ownership, reviewer anonymity and document history.
**Priority:** Normal.
**Planned implementation batch:** Later batch — scope and dependencies to be reviewed.
**Acceptance criteria:** Satisfy the requirement wording in the original heading and the Tests and Security/deps criteria in the verbatim entry; demonstrate role-appropriate behavior with relevant automated tests and user-facing/browser review where applicable. No audit coverage alone constitutes acceptance.

## Batch 1 evidence and limitations

Current `ManuscriptProgress.jsx` uses native disclosures for the supplied stages; `ManuscriptProgress.css` already had 24 px circles and four semantic states. This task added explicit missing/empty stage messages and long-label flex safeguards, and added focused tests. A role-filtered API must remain the authority. The browser keyboard toggle, real responsive layout and computed color contrast were not independently verified. Requirement 20 remains In Progress for keyboard/role coverage; requirement 21 remains In Progress for cross-workspace repetition and browser review.

Build executed: `npm run build -- --outDir /private/tmp/gsub-47-batch1-build-final-20261118 --emptyOutDir=false` — passed. Tests and build use synthetic fixtures and no configured database.
