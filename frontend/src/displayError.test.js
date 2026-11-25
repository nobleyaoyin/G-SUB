import {expect,it} from 'vitest';
import {displayError} from './displayError';
it('hides internal schema terminology without suppressing actionable failures',()=>{
 expect(displayError('Distribution schema unavailable')).toBe('This information is currently unavailable.');
 expect(displayError('EIC proof schema unavailable')).toBe('This information is currently unavailable.');
 expect(displayError('Upload failed: invalid file')).toBe('Upload failed: invalid file');
 expect(displayError('Saved, but schema unavailable; do not retry.')).toBe('Saved, but information is unavailable; do not retry.');
});
