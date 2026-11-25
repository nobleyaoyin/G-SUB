
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import AIPrescreeningPanel from "./AIPrescreeningPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mockResponse(submissions) {
  return {
    ok: true,
    json: async () => ({ advisory_only: true, submissions }),
  };
}

function renderPanel(manuscriptId = 1) {
  return render(
    createElement(AIPrescreeningPanel, {
      manuscriptId,
      token: "synthetic-test-token",
    })
  );
}

describe("AI Prescreening Panel", () => {
  it("shows pending status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockResponse([{
        snapshot_id: "snapshot-1",
        submission_sequence: 1,
        submission_kind: "initial",
        review_round: 1,
        file_format: "txt",
        status: "pending",
        analysis: null,
      }])
    ));

    renderPanel();

    expect(await screen.findByText(/AI status:/)).toBeTruthy();
    expect(screen.getByText("Pending")).toBeTruthy();
  });

  it("shows completed findings", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockResponse([{
        snapshot_id: "snapshot-1",
        submission_sequence: 1,
        submission_kind: "initial",
        review_round: 1,
        file_format: "txt",
        status: "completed",
        analysis: {
          engine: "local_rules_v1",
          word_count: 120,
          sections_detected: ["abstract", "introduction"],
          findings: [{
            code: "missing_methods",
            severity: "warning",
            message: "Methods section not detected.",
          }],
        },
      }])
    ));

    renderPanel();

    expect(await screen.findByText("Methods section not detected.")).toBeTruthy();
    expect(
      screen.getByText((_, element) =>
        element?.tagName === "P" &&
        element.textContent.includes("Word count:") &&
        element.textContent.includes("120")
      )
    ).toBeTruthy();
    expect(screen.getByText("abstract, introduction")).toBeTruthy();
    expect(screen.getByText(/Advisory only/)).toBeTruthy();
  });

  it("shows empty results", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse([])));

    renderPanel();

    expect(await screen.findByText(
      /No AI prescreening results are available/
    )).toBeTruthy();
  });

  it("shows API errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
    }));

    renderPanel();

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/AI report request failed/)).toBeTruthy();
  });

  it("ignores stale responses after manuscript changes", async () => {
    let resolveOld;

    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise(resolve => {
        resolveOld = resolve;
      }))
      .mockResolvedValueOnce(mockResponse([]));

    vi.stubGlobal("fetch", fetchMock);

    const view = renderPanel(1);

    view.rerender(
      createElement(AIPrescreeningPanel, {
        manuscriptId: 2,
        token: "synthetic-test-token",
      })
    );

    await screen.findByText(
      /No AI prescreening results are available/
    );

    resolveOld(mockResponse([{
      snapshot_id: "old-snapshot",
      submission_sequence: 99,
      submission_kind: "initial",
      review_round: 1,
      file_format: "txt",
      status: "completed",
      analysis: null,
    }]));

    await waitFor(() => {
      expect(screen.queryByText("Submission #99")).toBeNull();
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
