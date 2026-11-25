import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import SubmissionWizard from './SubmissionWizard';

afterEach(cleanup);

it('explains informational Unicode counts and associates them with metadata fields',async()=>{
 const onCreateDraft=vi.fn().mockResolvedValue({manuscript_id:12});
 render(<SubmissionWizard onCreateDraft={onCreateDraft} onUpdateDraft={vi.fn()} onUploadFile={vi.fn()} onClose={vi.fn()}/>);
 const title=screen.getByLabelText(/Manuscript Title/),abstract=screen.getByLabelText(/Abstract/);
 expect(title.getAttribute('aria-describedby')).toContain('wizard-title-count');
 expect(abstract.getAttribute('aria-describedby')).toContain('wizard-count-method');
 expect(screen.getByText(/Words are separated by whitespace/).textContent).toContain('informational, not submission limits');
 fireEvent.change(title,{target:{value:'  Étude 🌍  '}});
 fireEvent.change(abstract,{target:{value:'Résumé\n研究  🌍'}});
 expect(screen.getByText('3 words · 12 characters (display count)')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Save & Continue'}));
 await screen.findByText('Upload Manuscript');
 expect(onCreateDraft).toHaveBeenCalledWith({title:'Étude 🌍',abstract:'Résumé\n研究  🌍'});
});

it('links existing required-field feedback to the affected controls',async()=>{
 render(<SubmissionWizard onCreateDraft={vi.fn()} onUpdateDraft={vi.fn()} onUploadFile={vi.fn()} onClose={vi.fn()}/>);
 const title=screen.getByLabelText(/Manuscript Title/),abstract=screen.getByLabelText(/Abstract/);
 fireEvent.submit(screen.getByRole('button',{name:'Save & Continue'}).closest('form'));
 expect(await screen.findByRole('alert')).toHaveProperty('id','wizard-error');
 expect(title.getAttribute('aria-invalid')).toBe('true');
 expect(abstract.getAttribute('aria-invalid')).toBe('true');
 expect(title.getAttribute('aria-describedby')).toContain('wizard-error');
 expect(abstract.getAttribute('aria-describedby')).toContain('wizard-error');
});
