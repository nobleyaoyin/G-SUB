import {workflowMilestoneLabel, workflowStageLabel} from './workflowStatus';
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import ManuscriptProgress from "./ManuscriptProgress";
import { readFileSync } from "node:fs";
import userEvent from "@testing-library/user-event";
const progressStyles = readFileSync("src/ManuscriptProgress.css", "utf8");

const names = ["Submission", "Initial Screening", "Initial Editing", "Peer Review", "EIC Decision", "Author Agreement", "Final Editing", "Formatting", "Publication"];
const steps = ["Editor Invitation", "Editor Submission", "Author Approval", "Editor Approval", "EIC Approval", "Pre-review Author Confirmation"];
const purposes = [
  "This stage covers manuscript preparation and submission.",
  "This stage covers the editorial team's initial assessment.",
  "This stage covers initial editing and associated approvals.",
  "This stage covers reviewer assignments and evaluations.",
  "This stage covers the editor-in-chief's editorial decision.",
  "This stage covers review of the applicable author agreement.",
  "This stage covers final editing and its review.",
  "This stage covers formatting and review of the manuscript.",
  "This stage represents publication of an accepted manuscript in the local prototype.",
];
const payload = id => ({ manuscript_id: id, title: `Synthetic ${id}`, review_round: 2, current_stage: id === 1 ? "Initial Editing" : null, next_action: "Check the workflow.", private_field: "CONFIDENTIAL", stages: names.map((name, index) => ({ name, state: id === 1 && index === 2 ? "current" : "unknown", ...(id === 1 && index === 2 ? { steps: steps.map(name => ({ name, state: "unknown" })) } : {}) })) });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('reports validated progress to its parent and withdraws it after a refresh failure', async () => {
  const onProgressChange=vi.fn();
  vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce({ok:true,json:async()=>payload(1)}).mockResolvedValue({ok:false}));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" onProgressChange={onProgressChange} />);
  await waitFor(()=>expect(onProgressChange).toHaveBeenCalledWith(expect.objectContaining({manuscript_id:1,current_stage:'Initial Editing'})));
  fireEvent.focus(window);
  expect(await screen.findByRole('alert')).toBeTruthy();
  await waitFor(()=>expect(onProgressChange.mock.calls.at(-1)[0]).toBeNull());
});

it.each([
  [undefined, "Workflow stage information is unavailable."],
  [[], "No workflow stages are listed in this view."],
])("explains missing or empty stage data without inventing stages", async (stages, message) => {
  const data = {...payload(1), stages};
  vi.stubGlobal("fetch", vi.fn(async () => ({ok: true, json: async () => data})));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  expect(await screen.findByText(message)).toBeTruthy();
  expect(screen.getByRole("list", {name: "Workflow timeline"}).children).toHaveLength(0);
});

it("focuses a native stage disclosure and toggles it without displaying restricted response fields", async () => {
  const data = payload(1);
  data.stages[0].reviewer_identity = "restricted reviewer";
  vi.stubGlobal("fetch", vi.fn(async () => ({ok: true, json: async () => data})));
  const user = userEvent.setup();
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" showTitle={false} />);
  const list = await screen.findByRole("list", {name: "Workflow timeline"});
  const summary = within(list).getByText("Submission").closest("summary");
  await user.tab();
  expect(document.activeElement).toBe(summary);
  await user.click(summary);
  expect(summary.parentElement.open).toBe(true);
  await user.click(summary);
  expect(summary.parentElement.open).toBe(false);
  expect(screen.queryByText("restricted reviewer")).toBeNull();
  expect(screen.queryByText("Synthetic 1 (#1)")).toBeNull();
});

it("keeps long stage labels wrappable and the status visible", async () => {
  const data = payload(1);
  data.stages = [{name: "A".repeat(160), state: "pending"}];
  vi.stubGlobal("fetch", vi.fn(async () => ({ok: true, json: async () => data})));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  expect(await screen.findByText("A".repeat(160))).toBeTruthy();
  expect(screen.getByText("Upcoming")).toBeTruthy();
  expect(progressStyles).toMatch(/\.progress-stage-row > span\s*\{[^}]*overflow-wrap:\s*anywhere/s);
  expect(progressStyles).toMatch(/\.progress-stage-row > strong\s*\{[^}]*flex-shrink:\s*0/s);
});

it("presents unverified history neutrally and expands only supplied milestones", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => payload(1) })));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  expect(await screen.findByText("Synthetic 1 (#1)")).toBeTruthy();
  expect(screen.getByText("Review round: 2")).toBeTruthy();
  expect(screen.getByText("Initial editing", { selector: ".progress-stage-row span" })).toBeTruthy();
  const timeline = screen.getByRole("list", { name: "Workflow timeline" });
  expect(timeline.children).toHaveLength(9);
  const summary = within(timeline).getByText("Initial editing").closest("summary");
  expect(summary.parentElement.open).toBe(false);
  fireEvent.click(summary);
  expect(summary.parentElement.open).toBe(true);
  expect(within(summary.parentElement).getByRole("heading", { name: "Milestones" })).toBeTruthy();
  expect(within(summary.parentElement).getByRole("list").children).toHaveLength(6);
  for (const name of steps) expect(within(summary.parentElement).getByText(workflowMilestoneLabel(name))).toBeTruthy();
  expect(screen.queryByText("CONFIDENTIAL")).toBeNull();
});

it("replaces progress on selection changes and handles read failures", async () => {
  const fetchMock = vi.fn(async url => url.includes('/2/') ? { ok: true, json: async () => payload(2) } : { ok: false });
  vi.stubGlobal("fetch", fetchMock);
  const { rerender } = render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  rerender(<ManuscriptProgress manuscriptId={2} token="synthetic" />);
  await waitFor(() => expect(screen.getByText("Synthetic 2 (#2)")).toBeTruthy());
  expect(
    screen.getAllByText("Status unavailable").length
  ).toBeGreaterThan(0);
  expect(screen.queryByText("Initial Editing milestones")).toBeNull();
  expect(fetchMock.mock.calls.every(([, options]) => !options.method || options.method === "GET")).toBe(true);
});

it('ignores a late response for a previously selected manuscript', async () => {
  let finishFirst;
  vi.stubGlobal('fetch', vi.fn(url => url.includes('/1/')
    ? new Promise(resolve => { finishFirst = resolve; })
    : Promise.resolve({ok:true,json:async()=>payload(2)})));
  const { rerender } = render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  rerender(<ManuscriptProgress manuscriptId={2} token="synthetic" />);
  expect(await screen.findByText('Synthetic 2 (#2)')).toBeTruthy();
  finishFirst({ok:true,json:async()=>payload(1)});
  await waitFor(() => expect(screen.queryByText('Synthetic 1 (#1)')).toBeNull());
  expect(screen.queryByRole('button',{name:/refresh/i})).toBeNull();
});

it('keeps the last progress visible on refresh failure and skips picker focus', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce({ok:true,json:async()=>payload(1)}).mockResolvedValue({ok:false});
  vi.stubGlobal('fetch', fetchMock);
  const suspended = {current:true};
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" suspendRefreshRef={suspended} />);
  expect(await screen.findByText('Synthetic 1 (#1)')).toBeTruthy();
  fireEvent.focus(window);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  suspended.current = false;
  fireEvent.focus(window);
  expect((await screen.findByRole('alert')).textContent).toContain('last available information');
  expect(screen.getByText('Synthetic 1 (#1)')).toBeTruthy();
});


it('suppresses the repeated title when embedded in a workspace', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>payload(1)})));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" showTitle={false} />);
  expect(await screen.findByText('Review round: 2')).toBeTruthy();
  expect(screen.queryByText('Synthetic 1 (#1)')).toBeNull();
});

it('provides an explanatory disclosure for every stage without inventing records', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>payload(2)})));
  render(<ManuscriptProgress manuscriptId={2} token="synthetic" />);
  const timeline = await screen.findByRole('list', {name:'Workflow timeline'});
  for (const name of names) {
    const disclosure = within(timeline).getByText(workflowStageLabel(name)).closest('details');
    fireEvent.click(disclosure.querySelector('summary'));
    expect(within(disclosure).getByRole('heading', {name:'Milestones'})).toBeTruthy();
    expect(disclosure.querySelector('.progress-stage-details > p')?.textContent).toBeTruthy();
    expect(within(disclosure).getByText('Detailed milestones are not included in this view.')).toBeTruthy();
    expect(within(disclosure).getByText("This stage's status cannot be verified from the available information.")).toBeTruthy();
  }
});

it.each(['pending', 'unknown'])('labels neutral stage purposes separately from %s milestone status', async state => {
  const data = payload(2);
  data.stages = names.map(name => ({name, state}));
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>data})));
  render(<ManuscriptProgress manuscriptId={2} token="synthetic" />);
  const timeline = await screen.findByRole('list', {name:'Workflow timeline'});
  names.forEach((name, index) => {
    const disclosure = within(timeline).getByText(workflowStageLabel(name)).closest('details');
    fireEvent.click(disclosure.querySelector('summary'));
    const purpose = disclosure.querySelector('.progress-stage-details > p');
    expect(purpose.textContent).toBe(`Stage purpose: ${purposes[index]}`);
    expect(purpose.textContent).not.toMatch(/\b(has|have|was|were|is recorded|has been|have been)\b/i);
    expect(within(disclosure).getByRole('heading', {name:'Milestones'})).toBeTruthy();
    expect(within(disclosure).getByText('Detailed milestones are not included in this view.')).toBeTruthy();
    expect(within(disclosure).getByText(state === 'pending' ? 'Upcoming' : 'Status unavailable')).toBeTruthy();
  });
});


it("renders all four states and honest stage disclosures", async () => {
  const data = payload(1);
  data.stages = [
    {name:"Submission", state:"completed", steps:[]},
    {name:"Initial Screening", state:"current", steps:[{name:"Editor assessment", state:"current"}]},
    {name:"Initial Editing", state:"pending"},
    {name:"Peer Review", state:"unknown"},
  ];
  vi.stubGlobal("fetch", vi.fn(async () => ({ok:true,json:async()=>data})));
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  const list = await screen.findByRole("list", {name:"Workflow timeline"});
  expect([...list.children].map(item => item.className)).toEqual(["progress-completed","progress-current","progress-pending","progress-unknown"]);
  for (const name of ["Submission", "Initial screening", "Initial editing", "Peer review"]) {
    const disclosure = within(list).getByText(name).closest("details");
    expect(disclosure.open).toBe(false);
    fireEvent.click(disclosure.querySelector("summary"));
    expect(disclosure.open).toBe(true);
    expect(within(disclosure).getByRole("heading", {name:"Milestones"})).toBeTruthy();
  }
  expect(screen.getByText("No milestones are listed for this stage.")).toBeTruthy();
  expect(screen.getAllByText("Detailed milestones are not included in this view.")).toHaveLength(2);
  expect(screen.getByText("This stage's status cannot be verified from the available information.")).toBeTruthy();
  expect(screen.getByText("Editor assessment")).toBeTruthy();
  expect(within(list).getByText('Initial screening').closest('details').querySelector('.progress-stage-details > p').textContent).toContain("This stage covers the editorial team's initial assessment.");
  expect(progressStyles).toMatch(/width:\s*24px/);
  expect(progressStyles).toMatch(/height:\s*24px/);
  expect(progressStyles).toMatch(/progress-pending::before\s*\{\s*border:\s*2px solid var\(--text-primary\)/);
  expect(readFileSync('src/index.css','utf8')).toMatch(/--text-primary:\s*#0f172a/);
  expect(progressStyles).toMatch(/progress-completed::before/);
  expect(progressStyles).toMatch(/progress-current::before/);
  expect(progressStyles).toMatch(/2px dashed var\(--control-border\)/);
  expect(readFileSync('src/index.css','utf8')).toMatch(/--control-border:\s*#64748b/);
});

it('withdraws progress immediately when authentication changes for the same manuscript', async () => {
  let resolveNew;
  vi.stubGlobal('fetch', vi.fn((url, options) => options.headers.Authorization === 'Bearer first'
    ? Promise.resolve({ok:true,json:async()=>payload(1)})
    : new Promise(resolve => { resolveNew = resolve; })));
  const {rerender} = render(<ManuscriptProgress manuscriptId={1} token="first" />);
  expect(await screen.findByText('Synthetic 1 (#1)')).toBeTruthy();
  rerender(<ManuscriptProgress manuscriptId={1} token="second" />);
  expect(screen.queryByText('Synthetic 1 (#1)')).toBeNull();
  resolveNew({ok:false});
  expect(await screen.findByRole('alert')).toBeTruthy();
});
it('can omit a round already displayed by the enclosing workspace', async () => {
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>payload(1)})));
  const {rerender}=render(<ManuscriptProgress manuscriptId={1} token="synthetic" showTitle={false} showRound={false} />);
  await screen.findByRole('list',{name:'Workflow timeline'});
  expect(screen.queryByText('Review round: 2')).toBeNull();
  expect(screen.queryByText('Synthetic 1 (#1)')).toBeNull();
  rerender(<ManuscriptProgress manuscriptId={1} token="synthetic" showTitle={false} />);
  expect(screen.getByText('Review round: 2')).toBeTruthy();
});

it('omits an empty summary when the workspace already supplies its context', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>payload(1)})));
  const {container} = render(<ManuscriptProgress manuscriptId={1} token="synthetic" showTitle={false} showRound={false} showNextAction={false} />);
  expect(await screen.findByLabelText('Workflow timeline')).toBeTruthy();
  expect(container.querySelector('.progress-summary')).toBeNull();
});

it('keeps errors and the publication caveat outside collapsed milestones', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({ok:true,json:async()=>payload(1)}).mockResolvedValue({ok:false}));
  const user = userEvent.setup();
  render(<ManuscriptProgress manuscriptId={1} token="synthetic" showTitle={false} showRound={false} collapseMilestones />);
  const summary = await screen.findByText('Workflow milestones');
  const disclosure = summary.closest('details');
  expect(disclosure.open).toBe(false);
  expect(screen.getByText('Check the workflow.')).toBeTruthy();
  expect(screen.getByText('Publication is a local prototype.').closest('details')).toBeNull();
  await user.click(summary);
  expect(disclosure.open).toBe(true);
  await user.click(summary);
  expect(disclosure.open).toBe(false);
  fireEvent.focus(window);
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toContain('last available information');
  expect(alert.closest('details')).toBeNull();
  expect(disclosure.open).toBe(false);
});

it.each([
  ['Submission', 1], ['Peer Review', 2], ['Publication', 3],
])('preserves %s stage and round %i in standalone and embedded views', async (stage, round) => {
  const data = {...payload(1), review_round: round, current_stage: stage,
    stages: names.map(name => ({name, state: name === stage ? 'current' : 'pending'}))};
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true, json:async()=>data})));
  const {rerender} = render(<ManuscriptProgress manuscriptId={1} token="synthetic" />);
  const list = await screen.findByRole('list', {name:'Workflow timeline'});
  expect(within(list).getByText(workflowStageLabel(stage)).closest('li').className).toBe('progress-current');
  expect(screen.getByText(`Review round: ${round}`)).toBeTruthy();
  expect(screen.getByText('Check the workflow.')).toBeTruthy();
  rerender(<ManuscriptProgress manuscriptId={1} token="synthetic" showTitle={false} showRound={false} showNextAction={false} />);
  expect(within(list).getByText(workflowStageLabel(stage)).closest('li').className).toBe('progress-current');
  expect(screen.queryByText(`Review round: ${round}`)).toBeNull();
  expect(screen.queryByText('Synthetic 1 (#1)')).toBeNull();
});
