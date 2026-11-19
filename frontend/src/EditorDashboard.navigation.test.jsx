import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

vi.mock('./NotificationBell', () => ({
  default: ({ onNavigate }) => (
    <button onClick={() => onNavigate({ manuscript_id: 2 })}>
      Navigate notification to Paper 2
    </button>
  ),
}));

vi.mock('./FormattingPanel', () => ({
  default: ({ onDirtyChange }) => (
    <div>
      <button onClick={() => onDirtyChange(true)}>
        Mark formatting dirty
      </button>
    </div>
  ),
}));

vi.mock('./FinalEditingPanel', () => ({ default: () => null }));
vi.mock('./InitialEditingPanel', () => ({ default: () => null }));
vi.mock('./ManuscriptProgress', () => ({ default: () => null }));
vi.mock('./ReviewerInvitationPanel', () => ({ default: () => null }));

import EditorDashboard from './EditorDashboard';

function mockResponse(body) {
  return {
    ok: true,
    headers: {
      get: () => 'application/json',
    },
    json: async () => body,
  };
}

function setup(registerManuscriptReturn) {
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    const endpoint = String(url);

    if (endpoint.endsWith('/manuscripts/dashboard')) {
      return mockResponse([]);
    }

    if (endpoint.endsWith('/manuscripts/dashboard/summary')) {
      return mockResponse({
        total_manuscripts: 0,
        not_assigned: 0,
        in_progress: 0,
        ready_for_decision: 0,
        revision_required: 0,
        decision_finalized: 0,
      });
    }

    if (endpoint.endsWith('/formatting/my')) {
      return mockResponse([1, 2].map(id => ({
        manuscript_id: id,
        title: `Paper ${id}`,
        status: 'formatting',
        invitations: [],
        submissions: [],
      })));
    }

    throw new Error(`Unexpected API request: ${endpoint}`);
  }));

  return render(
    <EditorDashboard
      user={{ name: 'Synthetic Editor' }}
      token="synthetic-token"
      registerManuscriptReturn={registerManuscriptReturn}
    />
  );
}

function getCard(id) {
  return screen.getByText(`Paper ${id}`).closest('.editor-card');
}

beforeEach(() => {
  vi.stubGlobal('confirm', vi.fn(() => false));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it('uses the manuscript ID for a blank selected title', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => {
    const path = String(url);
    if (path.endsWith('/manuscripts/dashboard')) return mockResponse([{manuscript_id:1,title:' ',status:'submitted'}]);
    if (path.endsWith('/manuscripts/dashboard/summary')) return mockResponse({});
    if (path.endsWith('/formatting/my')) return mockResponse([]);
    if (path.includes('/notes') || path.includes('/general-comments')) return mockResponse([]);
    throw new Error(`Unexpected API request: ${path}`);
  }));
  render(<EditorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button', {name:'Open manuscript'}));
  expect(screen.getByRole('heading', {name:'Manuscript #1'})).toBeTruthy();
  expect(within(screen.getByRole('heading', {name:'Manuscript #1'}).closest('[data-workspace=selected]')).getAllByText('Manuscript #1')).toHaveLength(1);
});

it('places separate notes and staff comments before the overview without losing drafts', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => {
    const path = String(url);
    if (path.endsWith('/manuscripts/dashboard')) return mockResponse([{manuscript_id:1,title:'Paper 1',status:'submitted'}]);
    if (path.endsWith('/manuscripts/dashboard/summary')) return mockResponse({});
    if (path.endsWith('/formatting/my')) return mockResponse([]);
    if (path.includes('/notes') || path.includes('/general-comments')) return mockResponse([]);
    throw new Error(`Unexpected API request: ${path}`);
  }));
  render(<EditorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button', {name:'Open manuscript'}));
  const notes = screen.getByText('Private Notes');
  const comments = screen.getByText('Comments (Staff Shared)');
  expect(screen.getAllByText('Private Notes')).toHaveLength(1);
  expect(screen.getAllByText('Comments (Staff Shared)')).toHaveLength(1);
  expect(comments.compareDocumentPosition(screen.getByText('Manuscript Overview')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(notes);
  const note=within(notes.closest('details')).getByLabelText('New note');
  fireEvent.change(note,{target:{value:'Private editor note'}});
  fireEvent.click(notes); fireEvent.click(notes);
  expect(within(notes.closest('details')).getByLabelText('New note').value).toBe('Private editor note');
  fireEvent.click(comments);
  const comment=within(comments.closest('details')).getByLabelText('Add a general comment');
  fireEvent.change(comment,{target:{value:'Staff draft'}});
  fireEvent.click(comments); fireEvent.click(comments);
  expect(within(comments.closest('details')).getByLabelText('Add a general comment').value).toBe('Staff draft');
  expect(screen.getByRole('button', {name:'Back to Manuscripts'})).toBeTruthy();
  expect(screen.getByText('Manuscript Overview')).toBeTruthy();
  expect(notes.closest('[data-workspace="selected"]')).toBe(comments.closest('[data-workspace="selected"]'));
});

it('opens and returns from a formatting-only manuscript', async () => {
  setup();

  const card = await screen.findByText('Paper 1');

  fireEvent.click(
    within(card.closest('.editor-card')).getByRole('button', {
      name: 'Open manuscript',
    })
  );

  expect(await screen.findByRole('button', {
    name: 'Back to Manuscripts',
  })).toBeTruthy();

  expect(screen.queryByText('Paper 2')).toBeNull();

  fireEvent.click(screen.getByRole('button', {
    name: 'Back to Manuscripts',
  }));

  expect(await screen.findByText('Paper 2')).toBeTruthy();
});

it('preserves formatting changes when manuscript navigation is cancelled', async () => {
  setup();

  const card = await screen.findByText('Paper 1');

  fireEvent.click(within(card.closest('.editor-card')).getByRole('button', {
    name: 'Open manuscript',
  }));

  fireEvent.click(await screen.findByRole('button', {
    name: 'Mark formatting dirty',
  }));

  fireEvent.click(screen.getByRole('button', {
    name: 'Back to Manuscripts',
  }));

  expect(window.confirm).toHaveBeenCalledOnce();
  expect(screen.getByRole('button', {
    name: 'Mark formatting dirty',
  })).toBeTruthy();
  expect(screen.queryByText('Paper 2')).toBeNull();
});

it('allows manuscript navigation after confirming discard', async () => {
  setup();

  const card = await screen.findByText('Paper 1');

  fireEvent.click(within(card.closest('.editor-card')).getByRole('button', {
    name: 'Open manuscript',
  }));

  fireEvent.click(await screen.findByRole('button', {
    name: 'Mark formatting dirty',
  }));

  window.confirm.mockReturnValue(true);

  fireEvent.click(screen.getByRole('button', {
    name: 'Back to Manuscripts',
  }));

  expect(await screen.findByText('Paper 2')).toBeTruthy();
});

it('preserves the current manuscript when notification navigation is cancelled', async () => {
  setup();

  const card = await screen.findByText('Paper 1');

  fireEvent.click(within(card.closest('.editor-card')).getByRole('button', {
    name: 'Open manuscript',
  }));

  fireEvent.click(await screen.findByRole('button', {
    name: 'Mark formatting dirty',
  }));

  fireEvent.click(screen.getByRole('button', {
    name: 'Navigate notification to Paper 2',
  }));

  expect(window.confirm).toHaveBeenCalledOnce();
  expect(screen.queryByText('Paper 2')).toBeNull();
  expect(screen.getByRole('button', {
    name: 'Mark formatting dirty',
  })).toBeTruthy();
});

it('allows notification navigation after confirming discard', async () => {
  setup();

  const card = await screen.findByText('Paper 1');

  fireEvent.click(within(card.closest('.editor-card')).getByRole('button', {
    name: 'Open manuscript',
  }));

  fireEvent.click(await screen.findByRole('button', {
    name: 'Mark formatting dirty',
  }));

  window.confirm.mockReturnValue(true);

  fireEvent.click(screen.getByRole('button', {
    name: 'Navigate notification to Paper 2',
  }));

  expect(await screen.findByRole('button', {
    name: 'Back to Manuscripts',
  })).toBeTruthy();

  expect(screen.getByText('Paper 2')).toBeTruthy();
  expect(screen.queryByText('Paper 1')).toBeNull();
});


it('registers the real editor return guard', async () => {
  let goBack; const register=handler=>{goBack=handler;return ()=>{};};
  setup(register);
  fireEvent.click(within((await screen.findByText('Paper 1')).closest('.editor-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByRole('button',{name:'Mark formatting dirty'}));
  act(()=>{expect(goBack()).toBe(false);});
  expect(screen.getByText('Paper 1').closest('[data-workspace=selected]')).toBeTruthy();
  window.confirm.mockReturnValueOnce(true);
  act(()=>{expect(goBack()).toBe(true);});
  expect(screen.getByText('Paper 2')).toBeTruthy();
});

it('shows recorded review submissions separately from reviewer comments', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => {
    const path = String(url);
    if (path.endsWith('/manuscripts/dashboard')) return mockResponse([{
      manuscript_id: 1, title: 'History Paper', status: 'ready_for_peer_review',
      review_round: 1, total_reviewers: 1, completed_reviews: 1, pending_reviews: 0,
    }]);
    if (path.endsWith('/manuscripts/dashboard/summary')) return mockResponse({});
    if (path.endsWith('/formatting/my')) return mockResponse([]);
    if (path.endsWith('/reviews/manuscript/1')) return mockResponse([{
      review_id: 7, assignment_id: 9, reviewer_id: 3, review_round: 1,
      comments: 'Private review text', recommendation: 'accept',
      submitted_at: '2026-11-01T12:00:00Z',
    }, {
      review_id: 8, assignment_id: 10, reviewer_id: 4, review_round: 2,
      comments: 'Other private review', recommendation: 'revision',
      submitted_at: '2026-11-03T12:00:00Z',
    }, {
      review_id: 9, assignment_id: 11, reviewer_id: 5, review_round: 3,
      comments: 'Undated private review', recommendation: 'accept', submitted_at: null,
    }]);
    if (path.includes('/notes') || path.includes('/general-comments')) return mockResponse([]);
    throw new Error(`Unexpected API request: ${path}`);
  }));
  render(<EditorDashboard user={{name:'Synthetic Editor'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('History Paper')).closest('.editor-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByRole('button',{name:'View Reviews'}));
  const history = (await screen.findByText('Activity History')).closest('details');
  fireEvent.click(within(history).getByText('Activity History'));
  expect(within(history).getByText(/Review submitted · Round 1/)).toBeTruthy();
  expect(within(history).queryByText('Private review text')).toBeNull();
  expect(within(history).queryByText('Other private review')).toBeNull();
  expect(within(history).getAllByRole('listitem').map(item => item.textContent.match(/Round \d/)[0])).toEqual(['Round 2', 'Round 1', 'Round 3']);
  expect(screen.getByText('Private review text')).toBeTruthy();
});

it('ignores an old token dashboard response after a new identity loads', async () => {
  let finishOld;
  vi.stubGlobal('fetch',vi.fn((url, options={}) => {
    const path=String(url), auth=options.headers?.Authorization;
    if (path.endsWith('/manuscripts/dashboard') && auth === 'Bearer old') return new Promise(resolve=>{finishOld=resolve;});
    if (path.endsWith('/manuscripts/dashboard')) return Promise.resolve(mockResponse([{manuscript_id:2,title:'New token paper',status:'submitted'}]));
    if (path.endsWith('/manuscripts/dashboard/summary')) return Promise.resolve(mockResponse({}));
    if (path.endsWith('/formatting/my')) return Promise.resolve(mockResponse([]));
    return Promise.resolve(mockResponse([]));
  }));
  const {rerender}=render(<EditorDashboard user={{name:'Synthetic'}} token="old" />);
  await waitFor(()=>expect(finishOld).toBeTypeOf('function'));
  rerender(<EditorDashboard user={{name:'Synthetic'}} token="new" />);
  expect(await screen.findByText('New token paper')).toBeTruthy();
  await act(async()=>finishOld(mockResponse([{manuscript_id:1,title:'Old token paper',status:'submitted'}])));
  expect(screen.queryByText('Old token paper')).toBeNull();
  expect(screen.getByText('New token paper')).toBeTruthy();
});

it('ignores an obsolete review-history error after selecting another manuscript', async () => {
  let failA;
  vi.stubGlobal('fetch',vi.fn(url=>{
    const path=String(url);
    if(path.endsWith('/manuscripts/dashboard')) return Promise.resolve(mockResponse([1,2].map(id=>({manuscript_id:id,title:`History paper ${id}`,status:'submitted',review_round:id}))));
    if(path.endsWith('/manuscripts/dashboard/summary')) return Promise.resolve(mockResponse({}));
    if(path.endsWith('/formatting/my')) return Promise.resolve(mockResponse([]));
    if(path.endsWith('/reviews/manuscript/1')) return new Promise((resolve,reject)=>{failA=reject;});
    return Promise.resolve(mockResponse([]));
  }));
  render(<EditorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(within((await screen.findByText('History paper 1')).closest('.editor-card')).getByRole('button',{name:'Open manuscript'}));
  fireEvent.click(screen.getByRole('button',{name:'View Reviews'}));
  await waitFor(()=>expect(failA).toBeTypeOf('function'));
  fireEvent.click(screen.getByRole('button',{name:'Back to Manuscripts'}));
  fireEvent.click(within(screen.getByText('History paper 2').closest('.editor-card')).getByRole('button',{name:'Open manuscript'}));
  await act(async()=>failA(new Error('OLD HISTORY FAILURE')));
  expect(screen.queryByText('OLD HISTORY FAILURE')).toBeNull();
  expect(screen.getByRole('heading',{name:'History paper 2'})).toBeTruthy();
});

it('uses a manuscript ID when a formatting-only editor assignment lacks a title', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => {
    const path=String(url);
    if (path.endsWith('/manuscripts/dashboard')) return mockResponse([]);
    if (path.endsWith('/manuscripts/dashboard/summary')) return mockResponse({});
    if (path.endsWith('/formatting/my')) return mockResponse([{manuscript_id:8,title:' ',status:'formatting',invitations:[{status:'accepted'}],submissions:[]}]);
    if (path.includes('/notes') || path.includes('/general-comments')) return mockResponse([]);
    throw new Error(`Unexpected API request: ${path}`);
  }));
  render(<EditorDashboard user={{name:'Synthetic'}} token="synthetic" />);
  fireEvent.click(await screen.findByRole('button',{name:'Open manuscript'}));
  expect(screen.getByRole('heading',{name:'Manuscript #8'})).toBeTruthy();
});
