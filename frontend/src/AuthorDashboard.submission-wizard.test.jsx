import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {webcrypto} from 'node:crypto';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import AuthorDashboard from "./AuthorDashboard";

beforeEach(()=>{const values=new Map();vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('localStorage',{getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,String(value)),removeItem:key=>values.delete(key),clear:()=>values.clear()});});

vi.mock("./NotificationBell", () => ({
  default: () => <div>Notification bell</div>,
}));

vi.mock("./InitialEditingPanel", () => ({
  default: () => <div>Initial editing workflow</div>,
}));

vi.mock("./AuthorAgreementPanel", () => ({
  default: () => <div>Agreement workflow</div>,
}));

vi.mock("./FinalEditingPanel", () => ({
  default: () => <div>Final editing workflow</div>,
}));

vi.mock("./FormattingPanel", () => ({
  default: () => <div>Formatting workflow</div>,
}));

vi.mock("./ManuscriptProgress", () => ({
  default: ({ manuscriptId }) => (
    <div>Progress details #{manuscriptId}</div>
  ),
}));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

const makeManuscript = (overrides = {}) => ({
  manuscript_id: 101,
  title: "Synthetic Research Paper",
  abstract: "Synthetic research abstract.",
  status: "draft",
  has_pdf: false,
  file_type: null,
  created_at: "2026-01-01T00:00:00",
  author_id: 1,
  ...overrides,
});

const jsonResponse = (data, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: new Headers({
    "content-type": "application/json",
  }),
  json: async () => data,
});

function setupFetch(initialManuscript = null, options = {}) {
  let manuscript = initialManuscript
    ? { ...initialManuscript }
    : null;

  let submitAttempts = 0;
  let guidedDraft = null;
  let uploadReceipt = null;

  const fetchMock = vi.fn(async (url, request = {}) => {
    const path = String(url);
    const method = request.method || "GET";

    if (path.endsWith('/author/submission-drafts/configuration')) return jsonResponse({submission_types:['Review Article']});
    if (path.endsWith('/author/submission-drafts/requirements')) return jsonResponse({keywords_required:true,cover_letter_required:false,corresponding_author_required:['first_name','last_name','email','institution','country'],coauthor_required:['first_name','last_name','institution','country']});
    if (path.endsWith('/author/submission-drafts') && method === 'GET') return jsonResponse(guidedDraft ? [guidedDraft] : []);
    if (path.endsWith('/author/submission-drafts') && method === 'POST') {guidedDraft={id:'guided',revision:0,current_step:1,payload:{}};return jsonResponse(guidedDraft,201);}
    if (path.endsWith('/author/submission-drafts/guided') && method === 'PUT') {const data=JSON.parse(request.body);guidedDraft={...guidedDraft,revision:guidedDraft.revision+1,current_step:data.current_step,payload:data.payload};return jsonResponse(guidedDraft);}
    if (path.endsWith('/author/submission-drafts/guided/link') && method === 'POST') {manuscript ||= makeManuscript({title:guidedDraft.payload.title,abstract:guidedDraft.payload.abstract});return jsonResponse({manuscript_id:101});}
    if (path.endsWith('/author/submission-drafts/guided/attachments') && method === 'GET') return jsonResponse([]);
    if (path.includes('/manuscripts/101/upload-requests/') && method === 'GET') return uploadReceipt ? jsonResponse(uploadReceipt) : jsonResponse({detail:'Not found'},404);
    if (path.endsWith('/manuscripts/101/upload-recovery') && method === 'GET') return jsonResponse({available:true});

    // Load the author's manuscript list.
    if (path.endsWith("/manuscripts/my")) {
      return jsonResponse(manuscript ? [manuscript] : []);
    }

    // Create a new manuscript draft.
    if (path.endsWith("/manuscripts/") && method === "POST") {
      manuscript = makeManuscript({
        manuscript_id: 101,
        title: JSON.parse(request.body).title,
        abstract: JSON.parse(request.body).abstract,
      });

      return jsonResponse(manuscript);
    }

    // Upload the manuscript file.
    if (
      path.endsWith("/manuscripts/101/upload") &&
      method === "POST"
    ) {
      const uploadedFile = request.body.get("file");
      const requestId = request.body.get('request_id');
      if (requestId) uploadReceipt = {request_id:requestId, manuscript_id:101, original_filename:uploadedFile.name, size:uploadedFile.size, sha256:JSON.parse(window.localStorage.getItem('gsub:pending-manuscript-upload:guided:101')).sha256, is_current:true};

      manuscript = {
        ...manuscript,
        has_pdf: true,
        file_type: uploadedFile.name.split(".").pop().toLowerCase(),
      };

      return jsonResponse({
        message: "File uploaded successfully",
      });
    }

    // Revalidate the uploaded manuscript.
    if (
      path.endsWith("/manuscripts/101") &&
      method === "GET"
    ) {
      return jsonResponse(manuscript);
    }

    // Submit the manuscript for review.
    if (
      path.includes("/manuscripts/101/submit") &&
      method === "POST"
    ) {
      submitAttempts += 1;

      if (
        options.failFirstSubmission &&
        submitAttempts === 1
      ) {
        return jsonResponse(
          { detail: "Temporary submission failure" },
          500
        );
      }

      manuscript = {
        ...manuscript,
        status: "submitted",
      };

      return jsonResponse(manuscript);
    }

    throw new Error(
      `Unexpected API request: ${method} ${path}`
    );
  });

  vi.stubGlobal("fetch", fetchMock);

  return {
    fetchMock,
    getManuscript: () => manuscript,
  };
}

function renderDashboard() {
  render(
    <AuthorDashboard
      user={{ name: "Synthetic Author" }}
      token="synthetic-token"
    />
  );
}

function getWizard() {
  const wizard = document.querySelector(".submission-wizard");

  if (!wizard) {
    throw new Error("Submission wizard was not rendered.");
  }

  return within(wizard);
}

async function resumeDraft(manuscript) {
  // Step 1: Find the manuscript in the list.
  const title = await screen.findByText(manuscript.title);
  const card = title.closest(".manuscript-card");

  if (!card) {
    throw new Error("Manuscript card was not found.");
  }

  // Step 2: Open manuscript details.
  fireEvent.click(
    within(card).getByRole("button", {
      name: "Open manuscript",
    })
  );

  // Step 3: Continue submission from the details page.
  const continueButton = await screen.findByRole("button", {
    name: "Continue Process",
  });

  fireEvent.click(continueButton);

  // Step 4: Wait for the submission wizard.
  return getWizard();
}

describe("AuthorDashboard - Submission Wizard Integration", () => {

  it("resumes an uploaded draft and submits it successfully", async () => {
    const manuscript = makeManuscript({
      has_pdf: true,
      file_type: "pdf",
    });

    const { fetchMock, getManuscript } =
      setupFetch(manuscript);

    renderDashboard();

    const wizard = await resumeDraft(manuscript);

    expect(
      wizard.getByText("Step 2 of 3")
    ).toBeTruthy();

    fireEvent.click(wizard.getByRole("button", {name: "Continue to Review"}));

    expect(
      wizard.getByRole("heading", {
        name: "Review Your Submission",
      })
    ).toBeTruthy();

    expect(
      wizard.getByText("Synthetic Research Paper")
    ).toBeTruthy();

    fireEvent.click(
      wizard.getByRole("button", {
        name: "Submit Manuscript",
      })
    );

    expect(
      await screen.findByText(
        "Manuscript Submitted Successfully!"
      )
    ).toBeTruthy();

    expect(getManuscript().status).toBe("submitted");

    expect(
      fetchMock.mock.calls.some(
        ([url, request]) =>
          String(url).includes("/manuscripts/101/submit") &&
          request.method === "POST"
      )
    ).toBe(true);
  });

  it.each([
    "paper.pdf",
    "paper.docx",
    "paper.doc",
    "paper.txt",
  ])(
    "resumes an incomplete draft and uploads %s",
    async (filename) => {
      const manuscript = makeManuscript({
        has_pdf: false,
      });

      const { fetchMock, getManuscript } =
        setupFetch(manuscript);

      renderDashboard();

      const wizard = await resumeDraft(manuscript);

      expect(
        wizard.getByText("Step 2 of 3")
      ).toBeTruthy();

      const input = wizard.getByLabelText(
        /Select Manuscript File/
      );

      const file = new File(
        ["Synthetic manuscript content"],
        filename
      );

      fireEvent.change(input, {
        target: { files: [file] },
      });

      fireEvent.click(
        wizard.getByRole("button", {
          name: "Upload File",
        })
      );

      await waitFor(() => {
        expect(
          wizard.getByRole("heading", {
            name: "Review Your Submission",
          })
        ).toBeTruthy();
      });

      expect(getManuscript().has_pdf).toBe(true);

      expect(getManuscript().file_type).toBe(
        filename.split(".").pop()
      );

      const uploadCall = fetchMock.mock.calls.find(
        ([url, request]) =>
          String(url).endsWith("/manuscripts/101/upload") &&
          request.method === "POST"
      );

      expect(uploadCall).toBeTruthy();

      expect(
        uploadCall[1].body.get("file").name
      ).toBe(filename);
    }
  );

  it("completes the entire new manuscript submission workflow", async () => {
    const {fetchMock,getManuscript}=setupFetch();renderDashboard();
    fireEvent.click(screen.getByRole('button',{name:'+ New Submission'}));
    const wizard=getWizard();
    await waitFor(()=>expect(wizard.getByRole('button',{name:'Start'}).disabled).toBe(false));
    fireEvent.click(wizard.getByRole('button',{name:'Start'}));await wizard.findByText(/Step 2 of 10/);
    fireEvent.change(wizard.getByLabelText(/Submission type/),{target:{value:'Review Article'}});fireEvent.click(wizard.getByRole('button',{name:'Next'}));await wizard.findByText(/Step 3 of 10/);
    fireEvent.change(wizard.getByLabelText(/Document title/),{target:{value:'New Synthetic Paper'}});fireEvent.click(wizard.getByRole('button',{name:'Next'}));await wizard.findByText(/Step 4 of 10/);
    fireEvent.change(wizard.getByLabelText(/^Abstract/),{target:{value:'New synthetic abstract.'}});fireEvent.click(wizard.getByRole('button',{name:'Next'}));await wizard.findByText(/Step 5 of 10/);
    await waitFor(()=>expect(getManuscript()?.title).toBe('New Synthetic Paper'));
    fireEvent.change(wizard.getByLabelText('Select manuscript file'),{target:{files:[new File(['New manuscript'],'new-paper.pdf')]}});fireEvent.click(wizard.getByRole('button',{name:'Upload manuscript'}));await wizard.findByText(/Current file:/);
    fireEvent.click(wizard.getByRole('button',{name:'Next'}));await wizard.findByText(/Step 6 of 10/);fireEvent.change(wizard.getByLabelText('Keyword'),{target:{value:'research'}});fireEvent.click(wizard.getByRole('button',{name:'Add keyword'}));fireEvent.click(wizard.getByRole('button',{name:'Next'}));await wizard.findByText(/Step 7 of 10/);
    const author=wizard.getByRole('group',{name:'Corresponding author'});for(const [label,value] of [['First name','Synthetic'],['Last name','Author'],['Email','author@example.com'],['Institution','University'],['Country','Country']])fireEvent.change(within(author).getByLabelText(new RegExp(`^${label}`)),{target:{value}});
    fireEvent.click(wizard.getByRole('button',{name:'Next'}));await wizard.findByText(/Step 8 of 10/);fireEvent.change(wizard.getByLabelText(/Corresponding author position/),{target:{value:'0'}});fireEvent.click(wizard.getByRole('button',{name:'Next'}));await wizard.findByText(/Step 9 of 10/);fireEvent.click(wizard.getByRole('button',{name:'Next'}));await wizard.findByText(/Step 10 of 10/);fireEvent.click(wizard.getByRole('button',{name:'Next'}));await wizard.findByRole('heading',{name:'Review and submit'});
    fireEvent.click(wizard.getByRole('button',{name:'Submit manuscript'}));expect(await screen.findByRole('heading',{name:'Submission successful'})).toBeTruthy();expect(getManuscript().status).toBe('submitted');
    expect(fetchMock.mock.calls.some(([url,request])=>String(url).endsWith('/author/submission-drafts')&&request.method==='POST')).toBe(true);
    expect(fetchMock.mock.calls.some(([url,request])=>String(url).includes('/manuscripts/101/submit')&&request.method==='POST'&&request.headers['X-Expected-Submission-Revision'])).toBe(true);
  });

  it("allows retry after a failed submission", async () => {
    const manuscript = makeManuscript({
      has_pdf: true,
      file_type: "pdf",
    });

    const { fetchMock, getManuscript } =
      setupFetch(manuscript, {
        failFirstSubmission: true,
      });

    renderDashboard();

    const wizard = await resumeDraft(manuscript);
    fireEvent.click(wizard.getByRole("button", {name: "Continue to Review"}));

    fireEvent.click(
      wizard.getByRole("button", {
        name: "Submit Manuscript",
      })
    );

    expect(
      await wizard.findByText(
        "Submission was not completed. Please try again."
      )
    ).toBeTruthy();

    expect(getManuscript().status).toBe("draft");

    fireEvent.click(
      wizard.getByRole("button", {
        name: "Submit Manuscript",
      })
    );

    expect(
      await screen.findByText(
        "Manuscript Submitted Successfully!"
      )
    ).toBeTruthy();

    expect(getManuscript().status).toBe("submitted");

    const submitCalls = fetchMock.mock.calls.filter(
      ([url, request]) =>
        String(url).includes("/manuscripts/101/submit") &&
        request.method === "POST"
    );

    expect(submitCalls).toHaveLength(2);
  });

});

it('keeps a dirty wizard on cancelled sidebar navigation and discards it only on confirmation', async () => {
  setupFetch();
  vi.stubGlobal('confirm', vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true));
  let goBack;
  const register = handler => { goBack = handler; return () => {}; };
  render(<AuthorDashboard user={{name:'Synthetic Author'}} token="synthetic-token" registerManuscriptReturn={register} />);
  fireEvent.click(screen.getByRole('button', {name:'+ New Submission'}));
  expect(screen.queryByRole('button', {name:'+ New Submission'})).toBeNull();
  await waitFor(()=>expect(getWizard().getByRole('button',{name:'Start'}).disabled).toBe(false));
  fireEvent.click(getWizard().getByRole('button',{name:'Start'}));
  await getWizard().findByText(/Step 2 of 10/);
  fireEvent.change(getWizard().getByLabelText(/Submission type/),{target:{value:'Review Article'}});
  fireEvent.click(getWizard().getByRole('button',{name:'Next'}));
  await getWizard().findByText(/Step 3 of 10/);
  fireEvent.change(getWizard().getByLabelText(/Document title/), {target:{value:'Unfinished work'}});
  await waitFor(() => expect(goBack).toBeTypeOf('function'));
  expect(goBack()).toBe(false);
  expect(getWizard().getByLabelText(/Document title/).value).toBe('Unfinished work');
  fireEvent.click(getWizard().getByRole('button',{name:'Exit without saving'}));
  expect(document.querySelector('.submission-wizard')).toBeNull();
});
