import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import AuthorDashboard from "./AuthorDashboard";

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

  const fetchMock = vi.fn(async (url, request = {}) => {
    const path = String(url);
    const method = request.method || "GET";

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
    name: "Continue Submission",
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
      wizard.getByText("Step 3 of 3")
    ).toBeTruthy();

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
    const { fetchMock, getManuscript } =
      setupFetch();

    renderDashboard();

    fireEvent.click(
      screen.getByRole("button", {
        name: "+ New Submission",
      })
    );

    const wizard = getWizard();

    fireEvent.change(
      wizard.getByLabelText(/Manuscript Title/),
      {
        target: {
          value: "New Synthetic Paper",
        },
      }
    );

    fireEvent.change(
      wizard.getByLabelText(/Abstract/),
      {
        target: {
          value: "New synthetic abstract.",
        },
      }
    );

    fireEvent.click(
      wizard.getByRole("button", {
        name: /Save & Continue/,
      })
    );

    await waitFor(() => {
      expect(
        wizard.getByText("Step 2 of 3")
      ).toBeTruthy();
    });

    expect(getManuscript().title).toBe(
      "New Synthetic Paper"
    );

    const file = new File(
      ["New manuscript"],
      "new-paper.pdf"
    );

    fireEvent.change(
      wizard.getByLabelText(/Select Manuscript File/),
      {
        target: { files: [file] },
      }
    );

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

    const requests = fetchMock.mock.calls;

    expect(
      requests.some(
        ([url, request]) =>
          String(url).endsWith("/manuscripts/") &&
          request.method === "POST"
      )
    ).toBe(true);

    expect(
      requests.some(
        ([url, request]) =>
          String(url).includes("/manuscripts/101/submit") &&
          request.method === "POST"
      )
    ).toBe(true);
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
  fireEvent.change(getWizard().getByLabelText(/Manuscript Title/), {target:{value:'Unfinished work'}});
  await waitFor(() => expect(goBack).toBeTypeOf('function'));
  expect(goBack()).toBe(false);
  expect(getWizard().getByLabelText(/Manuscript Title/).value).toBe('Unfinished work');
  fireEvent.click(getWizard().getByRole('button',{name:'Close submission wizard'}));
  expect(document.querySelector('.submission-wizard')).toBeNull();
});
