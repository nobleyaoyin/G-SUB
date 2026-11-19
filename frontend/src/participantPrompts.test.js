import { describe, expect, it } from 'vitest';
import { authorPrompt, eicPrompt, reviewerPrompt, initialEditingPrompt, finalEditingPrompt, formatterPrompt } from './participantPrompts';

const overview = (status, extra = {}) => ({manuscript:{status,review_round:1}, invitations:[], submissions:[], decisions:[], ...extra});

describe('EIC guidance', () => {
  it.each([
    ['submitted', 'Initial screening is pending', false],
    ['initial_scan_passed', 'initial editor assignment', false],
    ['pre_review_confirmation', 'Waiting for the author', false],
    ['revision_required', 'requested revision', false],
    ['awaiting_author_agreement', 'agreement', false],
    ['final_editing', 'information is unavailable', false],
    ['formatting', 'unavailable or may be stale', false],
    ['accepted', 'legacy workflow', false],
    ['published', 'local prototype', false],
    ['unrecognized', 'cannot be determined', false],
  ])('classifies %s', (status, expected, action) => {
    const result = eicPrompt(overview(status));
    expect(result.text.toLowerCase()).toContain(expected.toLowerCase());
    expect(Boolean(result.action)).toBe(action);
  });
  it('distinguishes pending and declined editor invitations', () => {
    expect(eicPrompt(overview('initial_editor_invited',{invitations:[{status:'pending'}]})).text).toContain('Waiting');
    expect(eicPrompt(overview('initial_editor_invited',{invitations:[{status:'declined'}]})).text).toContain('declined');
    expect(eicPrompt(overview('initial_editor_invited')).text).toContain('unavailable');
  });
  it('requires server decision eligibility and no existing round decision', () => {
    expect(eicPrompt(overview('ready_for_peer_review',{review_progress:{can_decide:true}})).action).toBe(true);
    expect(eicPrompt(overview('ready_for_peer_review',{review_progress:{can_decide:false,blocked_reason:'Reviews incomplete'}})).text).toContain('Reviews incomplete');
    expect(eicPrompt(overview('ready_for_peer_review')).action).toBeUndefined();
    expect(eicPrompt(overview('ready_for_peer_review',{review_progress:{can_decide:true},decisions:[{review_round:1}]})).action).toBeUndefined();
    expect(eicPrompt({...overview('ready_for_peer_review',{review_progress:{can_decide:true}}),manuscript:{status:'ready_for_peer_review',review_round:null}}).action).toBeUndefined();
    expect(eicPrompt(overview('submitted'),true).action).toBeUndefined();
  });
  it('recognizes a recorded editor approval without assuming other stages are complete', () => {
    expect(eicPrompt(overview('initial_editing',{submissions:[{status:'editor_approved'}]})).text).toContain('editor-approved');
    expect(eicPrompt(overview('initial_editing',{submissions:[]})).action).toBeUndefined();
  });
  it('uses final editor invitation and submission records', () => {
    const base = {final_invitations:[],final_workflow_submissions:[]};
    expect(eicPrompt(overview('final_editing',base)).text).toContain('not yet been invited');
    expect(eicPrompt(overview('final_editing',{...base,final_invitations:[{status:'pending'}]})).text).toContain('Waiting');
    expect(eicPrompt(overview('final_editing',{...base,final_invitations:[{status:'declined'}]})).text).toContain('declined');
    expect(eicPrompt(overview('final_editing',{...base,final_workflow_submissions:[{status:'pending_eic'}]})).text).toContain('awaiting EIC review');
    expect(eicPrompt(overview('final_editing',{...base,final_workflow_submissions:[{status:'pending_eic'}]})).action).toBeUndefined();
    expect(eicPrompt(overview('final_editing',{...base,final_workflow_submissions:[{status:'pending_author'}]})).text).toContain('author');
  });
  it('uses only matching formatting data and reports actual workflow states', () => {
    const o = {...overview('formatting'), manuscript:{manuscript_id:7,status:'formatting',review_round:1}};
    const f = {manuscript_id:7,status:'formatting',invitations:[],submissions:[]};
    expect(eicPrompt(o,false,f).text).toContain('No formatting invitation');
    expect(eicPrompt(o,false,{...f,invitations:[{status:'pending'}]}).text).toContain('Waiting for the formatter');
    expect(eicPrompt(o,false,{...f,invitations:[{status:'declined'}]}).text).toContain('declined');
    expect(eicPrompt(o,false,{...f,invitations:[{status:'accepted'}]}).text).toContain('assigned formatter');
    expect(eicPrompt(o,false,{...f,submissions:[{status:'pending_eic'}]}).text).toContain('awaiting EIC review');
    expect(eicPrompt(o,false,{...f,submissions:[{status:'pending_eic'}]}).action).toBeUndefined();
    expect(eicPrompt(o,false,{...f,submissions:[{status:'approved'}]}).text).toContain('approved');
    expect(eicPrompt(o,false,{...f,manuscript_id:8,submissions:[{status:'pending_eic'}]}).action).toBeUndefined();
    expect(eicPrompt(o,true,{...f,submissions:[{status:'pending_eic'}]}).action).toBeUndefined();
  });
});

describe('other participant guidance', () => {
  it.each([['draft','draft'],['submitted','awaiting'],['revision_required','requires revision'],['revised','revision was submitted'],['pre_review_confirmation','confirm'],['published','Publication'],['withdrawn','withdrawn']])('author %s', (status, text) => expect(authorPrompt({status})).toContain(text));
  it('does not suggest actions from stale author data', () => expect(authorPrompt({status:'draft'},true)).toContain('stale'));
  it('requires accepted editor assignment before recommending an upload', () => {
    const item = {status:'initial_editing',invitation:{status:'accepted'},submissions:[]};
    expect(initialEditingPrompt(item,'editor')).toContain('Current upload eligibility is unconfirmed');
    expect(initialEditingPrompt({...item,invitation:{status:'declined'}},'editor')).toContain('declined');
    expect(initialEditingPrompt({...item,invitation:{status:'expired'}},'editor')).not.toContain('Upload');
    expect(initialEditingPrompt(item,'editor',true)).toContain('stale');
  });
  it('distinguishes final editor invitation and submission states', () => {
    const item={status:'accepted',manuscript_status:'final_editing',submissions:[]};
    expect(finalEditingPrompt(item,'editor')).toContain('Current upload eligibility is unconfirmed');
    expect(finalEditingPrompt({...item,status:'declined'},'editor')).toContain('declined');
    expect(finalEditingPrompt({...item,status:'expired'},'editor')).not.toContain('Upload');
    expect(finalEditingPrompt({...item,submissions:[{status:'pending_eic'}]},'editor')).toContain('EIC');
  });
  it('requires an accepted formatter invitation before recommending a document submission', () => {
    const item={status:'formatting',invitations:[{status:'accepted'}],submissions:[]};
    expect(formatterPrompt(item)).toContain('Current submission eligibility is unconfirmed');
    expect(formatterPrompt({...item,invitations:[{status:'declined'}]})).toContain('declined');
    expect(formatterPrompt({...item,invitations:[{status:'expired'}]})).not.toContain('Prepare');
    expect(formatterPrompt({...item,submissions:[{status:'pending_author'}]})).toContain('Waiting for the author');
    expect(formatterPrompt(item,true)).toContain('stale');
  });
});

describe('reviewer guidance', () => {
  it.each([
    [{status:'assigned',invitation_status:'pending'}, 'review invitation is pending'],
    [{status:'assigned',invitation_status:'declined'}, 'declined'],
    [{status:'assigned',invitation_status:'accepted',review_file_available:true}, 'submission eligibility is unconfirmed'],
    [{status:'assigned',invitation_status:'accepted',review_file_available:false}, 'availability is unconfirmed'],
    [{status:'completed',invitation_status:'legacy'}, 'review is complete'],
    [{status:'assigned',invitation_status:'expired'}, 'unavailable'],
    [{status:'invalidated',invitation_status:'accepted'}, 'No current review action'],
  ])('uses assignment state', (assignment, text) => expect(reviewerPrompt(assignment)).toContain(text));
  it('does not recommend an action with stale data', () => expect(reviewerPrompt({status:'assigned',invitation_status:'accepted'},true)).toContain('stale'));
});

it('does not recommend action for a withdrawn manuscript', () => {
  const result = eicPrompt(overview('withdrawn'));
  expect(result.text).toContain('withdrawn');
  expect(result.action).toBeUndefined();
});
