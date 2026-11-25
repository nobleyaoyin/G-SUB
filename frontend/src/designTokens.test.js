import { expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

const css=readFileSync('src/index.css','utf8');
const token=name=>{
  const match=css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  if(!match) throw new Error(`Missing color token ${name}`);
  return match[1];
};
const luminance=hex=>{
  const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4);
  return 0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2];
};
const contrast=(a,b)=>{const [hi,lo]=[luminance(a),luminance(b)].sort((x,y)=>y-x);return (hi+0.05)/(lo+0.05);};

it('provides readable semantic text and action token pairs',()=>{
  for(const [fg,bg] of [['text-primary','surface-control'],['text-secondary','surface-control'],['disabled-text','disabled-surface'],['info-text','info-surface'],['sidebar-text','brand-navy']]) {
    expect(contrast(token(fg),token(bg))).toBeGreaterThanOrEqual(4.5);
  }
  expect(contrast('#ffffff',token('action-primary'))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(token('focus-ring'),token('surface-control'))).toBeGreaterThanOrEqual(3);
});

it('defines the shared semantic surface, interaction and status colors',()=>{
  for (const name of ['surface-page','surface-secondary','surface-elevated','surface-control',
    'text-primary','text-secondary','text-muted','border-subtle','control-border',
    'action-primary','action-primary-hover','action-primary-text','action-secondary-surface',
    'focus-ring','success-text','success-surface','warning-text','warning-surface',
    'error-text','error-surface','info-text','info-surface','disabled-text','disabled-surface']) {
    expect(token(name)).toMatch(/^#[0-9a-fA-F]{6}$/);
  }
  for (const [fg,bg] of [['success-text','success-surface'],['warning-text','warning-surface'],
    ['error-text','error-surface'],['action-primary-text','action-primary'],['text-muted','surface-elevated']]) {
    expect(contrast(token(fg),token(bg))).toBeGreaterThanOrEqual(4.5);
  }
  expect(contrast(token('control-border'),token('surface-control'))).toBeGreaterThanOrEqual(3);
});

it('keeps role-card and selected-sidebar boundaries distinguishable from both adjacent fills',()=>{
  expect(contrast(token('control-border'),'#0a1525')).toBeGreaterThanOrEqual(3);
  expect(contrast(token('control-border'),'#172536')).toBeGreaterThanOrEqual(3);
  expect(contrast(token('sidebar-focus'),token('brand-navy'))).toBeGreaterThanOrEqual(3);
  expect(contrast(token('sidebar-focus'),token('action-primary'))).toBeGreaterThanOrEqual(3);
});

it('keeps the shared role accents and gold brand mark readable',()=>{
  expect(contrast(token('brand-navy'),token('brand-gold'))).toBeGreaterThanOrEqual(4.5);
  for(const role of ['eic','editor','reviewer','author','formatter']) {
    expect(contrast(token(`role-${role}`),'#172536')).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token(`role-${role}`),token(`role-${role}-surface`))).toBeGreaterThanOrEqual(3);
  }
});

it('uses a visible focus ring in editing and formatting forms',()=>{
  const editing=readFileSync('src/InitialEditingPanel.css','utf8');
  expect(editing).toMatch(/\.initial-editing-form input:focus-visible[\s\S]*?outline:\s*3px solid var\(--focus-ring\)/);
  expect(editing).toMatch(/\.formatting-proof-form textarea:focus-visible[\s\S]*?outline:\s*3px solid var\(--focus-ring\)/);
});

it('keeps reviewer invitation and formatter controls visibly focusable',()=>{
  const invitation=readFileSync('src/ReviewerInvitationPanel.css','utf8');
  const formatting=readFileSync('src/FormattingPanel.css','utf8');
  expect(invitation).toMatch(/\.reviewer-directory-form select:focus-visible\s*\{[^}]*outline:\s*3px solid var\(--focus-ring\)/s);
  expect(invitation).toMatch(/\.reviewer-invitation-panel button:focus-visible\s*\{[^}]*outline:\s*3px solid var\(--focus-ring\)/s);
  expect(formatting).toMatch(/\.formatter-dashboard button:focus-visible\s*\{[^}]*outline:\s*3px solid var\(--focus-ring\)/s);
});
