import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import SubmissionWizard from "./SubmissionWizard";

afterEach(() => {
  cleanup();
});

function setup(overrides = {}) {
  const props = {
    onCreateDraft: vi.fn().mockResolvedValue({
      manuscript_id: 101,
    }),
    onUpdateDraft: vi.fn().mockResolvedValue({}),
    onUploadFile: vi.fn().mockResolvedValue({}),
    onClose: vi.fn(),
    ...overrides,
  };

  render(<SubmissionWizard {...props} />);

  return props;
}

function fillManuscriptInformation() {
  fireEvent.change(
    screen.getByLabelText(/Manuscript Title/),
    { target: { value: "Synthetic Research Paper" } }
  );

  fireEvent.change(
    screen.getByLabelText(/Abstract/),
    { target: { value: "This is a synthetic research abstract." } }
  );
}

async function continueToUpload() {
  fillManuscriptInformation();

  fireEvent.click(
    screen.getByRole("button", { name: /Save & Continue/ })
  );

  await screen.findByText("Upload Manuscript");
}

describe("SubmissionWizard - Step 1", () => {
  it("renders manuscript information fields", () => {
    setup();

    expect(screen.getByLabelText(/Manuscript Title/)).toBeTruthy();
    expect(screen.getByLabelText(/Abstract/)).toBeTruthy();
    expect(screen.getByText("Step 1 of 3")).toBeTruthy();
  });

  it("rejects empty manuscript information", async () => {
    const props = setup();

    fireEvent.submit(
      screen.getByRole("button", { name: /Save & Continue/ }).closest("form")
    );

    expect(
      await screen.findByText("Title and Abstract cannot be empty.")
    ).toBeTruthy();

    expect(props.onCreateDraft).not.toHaveBeenCalled();
  });

  it("creates a draft and moves to Step 2", async () => {
    const props = setup();

    await continueToUpload();

    expect(props.onCreateDraft).toHaveBeenCalledWith({
      title: "Synthetic Research Paper",
      abstract: "This is a synthetic research abstract.",
    });

    expect(screen.getByText("Draft #101")).toBeTruthy();
    expect(screen.getByText("Step 2 of 3")).toBeTruthy();
  });

  it("shows an error when draft creation fails", async () => {
    const props = setup({
      onCreateDraft: vi.fn().mockRejectedValue(
        new Error("Database unavailable")
      ),
    });

    fillManuscriptInformation();

    fireEvent.click(
      screen.getByRole("button", { name: /Save & Continue/ })
    );

    expect(
      await screen.findByText("Database unavailable")
    ).toBeTruthy();

    expect(props.onCreateDraft).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Step 1 of 3")).toBeTruthy();
  });
});

describe("SubmissionWizard - Step 2", () => {
  it('shows the actual selected file format and size before upload', async () => {
    setup();
    await continueToUpload();
    const file = new File(['synthetic'], 'article.txt', {type:'text/plain'});
    fireEvent.change(screen.getByLabelText(/Select Manuscript File/), {target:{files:[file]}});
    expect(screen.getByText('article.txt')).toBeTruthy();
    expect(screen.getByText('Format: TXT · Size: 9 bytes')).toBeTruthy();
  });
  it.each(["pdf", "docx", "doc", "txt"])(
    "accepts and uploads .%s files",
    async (extension) => {
      const props = setup();

      await continueToUpload();

      const file = new File(
        ["Synthetic manuscript content"],
        `paper.${extension}`,
        { type: "application/octet-stream" }
      );

      fireEvent.change(screen.getByLabelText(/Select Manuscript File/), {
        target: { files: [file] },
      });

      fireEvent.click(
        screen.getByRole("button", { name: "Upload File" })
      );

      await waitFor(() => {
        expect(props.onUploadFile).toHaveBeenCalledWith(101, file);
      });

      expect(
        await screen.findByText(file.name)
      ).toBeTruthy();
    }
  );

  it("rejects unsupported file extensions", async () => {
    setup();

    await continueToUpload();

    const file = new File(
      ["Invalid file"],
      "paper.exe"
    );

    const input = screen.getByLabelText(/Select Manuscript File/);

    fireEvent.change(input, {
      target: { files: [file] },
    });

    expect(
      await screen.findByText(
        "Only PDF, DOCX, DOC, and TXT files are allowed."
      )
    ).toBeTruthy();

    expect(
      screen.getByRole("button", { name: "Upload File" }).disabled
    ).toBe(true);
  });

  it("rejects empty files", async () => {
    setup();

    await continueToUpload();

    const file = new File([], "empty.pdf");

    const input = screen.getByLabelText(/Select Manuscript File/);

    fireEvent.change(input, {
      target: { files: [file] },
    });

    expect(
      await screen.findByText("The manuscript file is empty.")
    ).toBeTruthy();
  });

  it("rejects files larger than 10 MB", async () => {
    setup();

    await continueToUpload();

    const file = new File(
      [new Uint8Array(10 * 1024 * 1024 + 1)],
      "large.pdf"
    );

    const input = screen.getByLabelText(/Select Manuscript File/);

    fireEvent.change(input, {
      target: { files: [file] },
    });

    expect(
      await screen.findByText("The maximum file size is 10 MB.")
    ).toBeTruthy();
  });

  it("returns to Step 1 and preserves manuscript information", async () => {
    setup();

    await continueToUpload();

    fireEvent.click(
      screen.getByRole("button", { name: /Previous/ })
    );

    expect(screen.getByLabelText(/Manuscript Title/).value)
      .toBe("Synthetic Research Paper");

    expect(screen.getByLabelText(/Abstract/).value)
      .toBe("This is a synthetic research abstract.");

    expect(screen.getByText("Step 1 of 3")).toBeTruthy();
  });

  it("allows retry after upload failure", async () => {
    const props = setup({
      onUploadFile: vi.fn()
        .mockRejectedValueOnce(new Error("Upload failed"))
        .mockResolvedValueOnce({}),
    });

    await continueToUpload();

    const file = new File(["content"], "paper.pdf");

    const input = screen.getByLabelText(/Select Manuscript File/);

    fireEvent.change(input, {
      target: { files: [file] },
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Upload File" })
    );

    expect(await screen.findByText("Upload failed")).toBeTruthy();

    fireEvent.change(input, {
      target: { files: [file] },
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Upload File" })
    );

    await waitFor(() => {
      expect(props.onUploadFile).toHaveBeenCalledTimes(2);
    });
  });
});

describe("SubmissionWizard - Navigation", () => {
  it("closes the wizard when requested", () => {
    const props = setup();

    fireEvent.click(
      screen.getByRole("button", { name: "Close submission wizard" })
    );

    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("does not create duplicate drafts after continuing", async () => {
    const props = setup();

    await continueToUpload();

    expect(props.onCreateDraft).toHaveBeenCalledTimes(1);
  });
});

describe("SubmissionWizard - Resume Draft", () => {
  it("starts at Step 2 when the draft has no file", () => {
    setup({
      initialManuscript: {
        manuscript_id: 101,
        title: "Existing Draft",
        abstract: "Existing abstract",
        has_pdf: false,
      },
    });

    expect(screen.getByText("Step 2 of 3")).toBeTruthy();
    expect(screen.getByText("Draft #101")).toBeTruthy();
  });

  it("starts at Step 2 when the draft already has a file", () => {
    setup({
      initialManuscript: {
        manuscript_id: 102,
        title: "Uploaded Draft",
        abstract: "Existing abstract",
        has_pdf: true,
        file_type: "pdf",
      },
    });

    expect(screen.getByText("Step 2 of 3")).toBeTruthy();
    expect(screen.getByText("Upload Manuscript")).toBeTruthy();
    expect(screen.getByText("Uploaded Draft")).toBeTruthy();
  });
});

it('shows Unicode-aware display counts without inventing keyword or body rules',()=>{
  setup();
  fireEvent.change(screen.getByLabelText(/Abstract/),{target:{value:'Résumé 🌍 two'}});
  expect(screen.getByText('3 words · 12 characters (display count)')).toBeTruthy();
  expect(screen.getByText(/Keywords are not collected/)).toBeTruthy();
  expect(screen.getByText(/Body word count is unavailable/)).toBeTruthy();
});

it('protects unsaved information when closing', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
  const props = setup();
  fireEvent.change(screen.getByLabelText(/Manuscript Title/), {target:{value:'Unsaved title'}});
  fireEvent.click(screen.getByRole('button', {name:'Close submission wizard'}));
  expect(props.onClose).not.toHaveBeenCalled();
  expect(screen.getByLabelText(/Manuscript Title/).value).toBe('Unsaved title');
  fireEvent.click(screen.getByRole('button', {name:'Close submission wizard'}));
  expect(props.onClose).toHaveBeenCalledOnce();
  confirm.mockRestore();
});

it('allows closing a saved draft without a discard prompt', async () => {
  const confirm = vi.spyOn(window, 'confirm');
  const props = setup();
  await continueToUpload();
  fireEvent.click(screen.getByRole('button', {name:'Save Draft & Exit'}));
  expect(confirm).not.toHaveBeenCalled();
  expect(props.onClose).toHaveBeenCalledOnce();
  confirm.mockRestore();
});
