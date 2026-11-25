import {describe,expect,it} from 'vitest';
import {documentExtension,originalDocumentName,downloadFilename} from './documentNames';

describe('safe document display metadata',()=>{
 it('uses only an explicit, safe original filename',()=>{
  expect(originalDocumentName({original_filename:' My Paper.docx '})).toBe('My Paper.docx');
  for(const name of [null,'','../private.docx','folder\\private.docx','bad\nname.pdf','..']) expect(originalDocumentName({original_filename:name})).toBeNull();
  expect(originalDocumentName({filename:'d1533d5dc86f4521b1e0e2e3321db643.docx'})).toBeNull();
 });
 it('derives only supported format labels without displaying a storage name',()=>{
  expect(documentExtension({filename:'d1533d5dc86f4521b1e0e2e3321db643.docx'})).toBe('docx');
  expect(documentExtension({file_format:'PDF'})).toBe('pdf');
  expect(documentExtension({filename:'odd.exe'})).toBeNull();
 });
 it('decodes UTF-8 download filenames exactly once and rejects unsafe names',()=>{
  expect(downloadFilename('attachment; filename="manuscript.txt"; filename*=UTF-8\'\'%E7%A0%94%E7%A9%B6.txt')).toBe('研究.txt');
  expect(downloadFilename('attachment; filename="safe.txt"; filename*=UTF-8\'\'%252e.txt')).toBe('%2e.txt');
  expect(downloadFilename('attachment; filename*=UTF-8\'\'%2E%2E%2Fbad.txt')).toBeNull();
  expect(downloadFilename('attachment; filename*=UTF-8\'\'%ZZ')).toBeNull();
 });
});

describe('filename safety parity',()=>{
 it('accepts multilingual, punctuation, missing and multiple extensions without rewriting historical names',()=>{
  for(const name of ['研究論文_測試版本.docx','研究データ_最終版.txt','한국어_문서.doc','Résumé_Final.docx','Paper Version (Final) 2026.pdf','archive.final.docx','no-extension','😀.txt','Re\u0301sume\u0301.txt']) expect(originalDocumentName({original_filename:name})).toBe(name);
 });
 it('rejects unsafe controls, paths, reserved names and oversized names',()=>{
  for(const name of ['../x.txt','folder\\x.txt','\nname.txt','bad\u0085.txt','bad\u007f.txt','CON.txt','con .pdf','COM1.doc','Lpt³.txt','NUL','foo.','a'.repeat(256)+'.txt','a:b.txt','a?.txt']) expect(originalDocumentName({original_filename:name})).toBeNull();
 });
 it('prefers extended UTF-8 over fallback and decodes once',()=>{
  expect(downloadFilename('attachment; filename="document.txt"; filename*=UTF-8\'\'Re%CC%81sume%CC%81.txt')).toBe('Re\u0301sume\u0301.txt');
  expect(downloadFilename('attachment; filename="document.txt"; filename*=UTF-8\'\'%252F.txt')).toBe('%2F.txt');
  expect(downloadFilename('attachment; filename*=UTF-8\'\'bad%C2%85.txt')).toBeNull();
 });
});
