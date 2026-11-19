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
