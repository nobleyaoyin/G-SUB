import {expect,it} from 'vitest';
import {readableRecordedDate,recordedMessage,recordedRole} from './recordedDisplay';
it('formats valid timestamps without inventing a missing timezone',()=>{
 expect(readableRecordedDate('2026-11-21T15:31:32.123456')).toMatch(/2026.*3:31.*timezone not recorded/i);
 expect(readableRecordedDate('2026-11-21 15:31:32.123456')).toMatch(/2026.*3:31.*timezone not recorded/i);
 expect(readableRecordedDate('2026-02-30T12:30:00')).toBe('');
 expect(readableRecordedDate(null)).toBe('');
});
it('normalizes only known generated role labels while preserving free text',()=>{
 expect(recordedMessage('AUTHOR reviewed final editing submission #1: approve.')).toBe('Author reviewed final editing submission #1: approve.');
 expect(recordedMessage('AUTHOR said hello to Dr. JOHN SMITH')).toBe('AUTHOR said hello to Dr. JOHN SMITH');
 expect(recordedRole('EIC')).toBe('EIC');expect(recordedRole('JOHN SMITH')).toBe('JOHN SMITH');
});
