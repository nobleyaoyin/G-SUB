"""Five-role browser rehearsal against a new synthetic local database."""
import os, signal, subprocess, sys, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.a6_browser_acceptance import ROOT, port, ready

def run():
    backend,frontend=port(),port()
    if backend==frontend: raise RuntimeError('Duplicate test ports')
    base=f'http://127.0.0.1:{backend}'; origin=f'http://127.0.0.1:{frontend}'
    processes=[]
    with tempfile.TemporaryDirectory(prefix='gsub-rehearsal-') as tmp, tempfile.TemporaryFile(mode='w+') as log:
        env=os.environ.copy();env.update(REHEARSAL_ROOT=tmp,REHEARSAL_PORT=str(backend),PYTHONPATH=str(ROOT),PYTHON_DOTENV_DISABLED='1',PYTHONDONTWRITEBYTECODE='1',VITE_API_PROXY_TARGET=base)
        try:
            server=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'tests/five_role_rehearsal_server.py')],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True);processes.append(server);ready(server,base+'/health')
            vite=subprocess.Popen(['npm','run','dev','--','--host','127.0.0.1','--port',str(frontend),'--strictPort'],cwd=ROOT/'frontend',env=env,stdout=log,stderr=log,start_new_session=True);processes.append(vite);ready(vite,origin)
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True); pages={}
                def screenshot(page,name):
                    if os.environ.get('REHEARSAL_SCREENSHOTS') != '1': return
                    target=ROOT/'reports'/name
                    with target.open('xb') as output: output.write(page.screenshot(full_page=True))
                for role,label in [('author','Author / Submitter'),('editor','Editor'),('eic','Editor-in-Chief'),('reviewer','Peer Reviewer'),('reviewer2','Peer Reviewer'),('reviewer3','Peer Reviewer'),('formatter','Formatter')]:
                    ctx=browser.new_context(accept_downloads=True);ctx.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                    page=ctx.new_page();page.set_default_timeout(10000);page.on('dialog',lambda dialog:dialog.accept());page.goto(origin);page.get_by_role('button',name=label,exact=True).click();page.locator('#email').fill(f'{role}@example.com');page.locator('#password').fill('Synthetic-Rehearsal-Password-472!');page.get_by_role('button',name='Sign In').click();page.get_by_text({'eic':'EIC Dashboard','reviewer2':'Reviewer Dashboard','reviewer3':'Reviewer Dashboard'}.get(role,role.title()+' Dashboard'),exact=False).first.wait_for();pages[role]=page
                    if role not in ('reviewer2','reviewer3'): screenshot(page,f'step_128_27_85_synthetic_{role}.png')
                author,editor,eic=pages['author'],pages['editor'],pages['eic']; title='Synthetic complete rehearsal'
                assert author.evaluate("async () => (await fetch('/api/users/me/reviewer-profile',{headers:{Authorization:'Bearer '+sessionStorage.getItem('access_token')}})).status") == 403
                assert author.evaluate("async () => (await fetch('/api/eic/manuscripts/1/online-text/initial',{headers:{Authorization:'Bearer '+sessionStorage.getItem('access_token')}})).status") == 403
                profile_page=pages['reviewer'];profile_page.get_by_role('button',name='My Professional Profile').click();profile=profile_page.get_by_role('region',name='My Professional Profile');profile.get_by_label('Professional Title').fill('Professor');profile.get_by_label('Institution / Affiliation').fill('Synthetic University');profile.get_by_label('Research Areas').fill('Synthetic research');profile.get_by_role('button',name='Save profile').click();profile.get_by_text('Professional profile saved.').wait_for();print('PASS reviewer self-reported profile',flush=True)
                author.get_by_role('button',name='+ New Draft').click();author.get_by_label('Title').fill(title);author.get_by_label('Abstract').fill('Synthetic abstract');author.get_by_role('button',name='Save Draft').click();author.get_by_text(title,exact=True).first.wait_for()
                card=author.locator('.manuscript-card').filter(has_text=title);card.get_by_role('button',name='Open manuscript').click();card.locator('li.progress-current').filter(has_text='Submission').wait_for();card.locator('input[type=file]').set_input_files({'name':'submission.txt','mimeType':'text/plain','buffer':b'Synthetic original manuscript'})
                card.get_by_role('button',name='Edit document (TXT)').click();online=card.get_by_role('region',name='Online manuscript editor');online.get_by_label('Document text').fill('Synthetic browser-edited manuscript');online.get_by_role('button',name='Save Version').click();online.get_by_text('Version saved.',exact=False).wait_for();online.get_by_text('Version History').click();online.get_by_text('Version 1',exact=False).wait_for();online.get_by_role('button',name='Cancel').click();card.get_by_role('button',name='Submit Manuscript').click();author.get_by_text('submitted',exact=True).first.wait_for();print('PASS author draft, TXT edit, history and submission',flush=True)
                def open_eic():
                    eic.reload();eic.get_by_role('button',name=f'#1 {title}').click();eic.locator('ol[aria-label="Workflow timeline"]').wait_for()
                def open_author():
                    author.reload();card=author.locator('.manuscript-card').filter(has_text=title);card.get_by_role('button',name='Open manuscript').click();card.locator('ol[aria-label="Workflow timeline"]').wait_for()
                def decide(form,choice,button):
                    form.get_by_label('Decision').select_option(choice);form.get_by_label('Comments').fill('Synthetic approval');form.get_by_role('button',name=button).click()
                open_eic();eic.locator('li.progress-current').filter(has_text='Initial Screening').wait_for();form=eic.locator('form').filter(has_text='Initial screening');decide(form,'pass','Record screening');form=eic.locator('form').filter(has_text='Invite initial editor');form.get_by_label('Editor').select_option(label='Synthetic Editor');form.get_by_role('button',name='Send invitation').click();print('PASS EIC screening and editor invitation',flush=True)
                editor.reload();panel=editor.get_by_role('region',name='Initial editing workflow');panel.get_by_role('button',name='Accept invitation').click();panel.locator('form').filter(has_text='Upload initial-editing document').wait_for();editor.reload();editor_card=editor.locator('.editor-card').filter(has_text=title);editor_card.get_by_role('button',name='Open manuscript').click();editor_card.locator('ol[aria-label="Workflow timeline"]').wait_for();panel=editor_card.get_by_role('region',name='Initial editing workflow');panel.get_by_role('button',name='Edit document (TXT)').click();online=panel.get_by_role('region',name='Online manuscript editor');assert online.get_by_label('Document text').input_value()=='Synthetic browser-edited manuscript';online.get_by_label('Document text').fill('Synthetic initial edit');online.get_by_role('button',name='Save Version').click();online.get_by_text('Version saved.',exact=False).wait_for();online.get_by_text('Version History').click();
                with editor.expect_download() as draft_download: online.get_by_role('button',name='Download').first.click()
                assert Path(draft_download.value.path()).read_bytes()==b'Synthetic initial edit'
                preserved=editor.evaluate("""async () => {const h={Authorization:'Bearer '+sessionStorage.getItem('access_token')}; const m=await (await fetch('/api/manuscripts/1',{headers:h})).json();const original=await (await fetch('/api/manuscripts/1/download',{headers:h})).text();return {status:m.status,original};}""")
                assert preserved=={'status':'initial_editing','original':'Synthetic browser-edited manuscript'}
                online.get_by_role('button',name='Use saved draft').click();panel.get_by_text('Saved online TXT draft selected.').wait_for();form=panel.locator('form').filter(has_text='Upload initial-editing document');form.get_by_label('Editing comments').fill('Synthetic edit');form.get_by_role('button',name='Submit initial-editing document').click()
                open_author();panel=author.get_by_role('region',name='Initial editing workflow');form=panel.locator('form').filter(has_text='Review initial editing');decide(form,'approve','Submit author review')
                editor.reload();panel=editor.get_by_role('region',name='Initial editing workflow');form=panel.locator('form').filter(has_text='Editor approval');decide(form,'approve','Submit editor approval')
                open_eic();form=eic.locator('form').filter(has_text='Review initial editing submission');decide(form,'approve','Record editing decision')
                open_author();panel=author.get_by_role('region',name='Initial editing workflow');form=panel.locator('form').filter(has_text='Confirm pre-review version');decide(form,'confirm','Submit confirmation');print('PASS initial editing and confirmation',flush=True)
                open_eic();eic.locator('li.progress-current').filter(has_text='Peer Review').wait_for();panel=eic.get_by_role('region',name='Reviewer invitations')
                for uid,email in [(4,'reviewer@example.com'),(5,'reviewer2@example.com')]:
                    panel.get_by_label('Search reviewers by name or email').fill(email);choice=panel.get_by_role('combobox');choice.locator(f'option[value="{uid}"]').wait_for(state='attached');choice.select_option(str(uid));
                    if uid==4: panel.get_by_text('Synthetic University',exact=True).wait_for()
                    panel.get_by_role('button',name='Invite reviewer',exact=True).click();panel.get_by_text('Reviewer invitation sent.').wait_for()
                for role in ('reviewer','reviewer2'):
                    page=pages[role];page.reload();page.locator('.notification-bell').click();page.get_by_text('You have a reviewer invitation.',exact=False).first.wait_for();page.locator('.notification-bell').click();card=page.locator('.reviewer-card').filter(has_text=title);card.get_by_role('button',name='Open manuscript').click();card.get_by_role('button',name='Accept review invitation').click();card.locator('ol[aria-label="Workflow timeline"]').wait_for()
                    assert page.evaluate("async () => (await fetch('/api/manuscripts/1/download',{headers:{Authorization:'Bearer '+sessionStorage.getItem('access_token')}})).status") == 403
                    with page.expect_download() as download:card.get_by_role('button',name='Download Review File').click()
                    assert Path(download.value.path()).read_bytes()==b'Synthetic initial edit'
                    card.get_by_label('Review Comments').fill('Synthetic review');card.get_by_label('Recommendation').select_option('accept' if role=='reviewer' else 'reject');card.get_by_role('button',name='Submit Review').click();card.get_by_text('Review already submitted.').wait_for()
                open_eic();summary=eic.get_by_role('region',name='Split review status');summary.get_by_text('Opposing accept and reject',exact=False).wait_for();panel=eic.get_by_role('region',name='Reviewer invitations');panel.get_by_label('Search reviewers by name or email').fill('reviewer3@example.com');choice=panel.get_by_role('combobox');choice.locator('option[value="6"]').wait_for(state='attached');choice.select_option('6');panel.get_by_role('button',name='Invite additional reviewer').click();panel.get_by_text('Reviewer invitation sent.').wait_for()
                page=pages['reviewer3'];page.reload();page.locator('.notification-bell').click();page.get_by_text('You have a reviewer invitation.',exact=False).first.wait_for();page.locator('.notification-bell').click();card=page.locator('.reviewer-card').filter(has_text=title);card.get_by_role('button',name='Open manuscript').click();card.get_by_role('button',name='Accept review invitation').click();card.locator('ol[aria-label="Workflow timeline"]').wait_for()
                with page.expect_download() as download:card.get_by_role('button',name='Download Review File').click()
                assert Path(download.value.path()).read_bytes()==b'Synthetic initial edit'
                card.get_by_label('Review Comments').fill('Synthetic additional review');card.get_by_label('Recommendation').select_option('revision');card.get_by_role('button',name='Submit Review').click();card.get_by_text('Review already submitted.').wait_for();open_eic();eic.get_by_role('region',name='Split review status').get_by_text('3 eligible completed reviews',exact=False).wait_for();print('PASS reviewers, 50/50 split and additional review',flush=True)
                open_eic();form=eic.locator('form').filter(has_text='Editorial decision for round');decide(form,'accept','Record editorial decision')
                open_author();author.locator('li.progress-current').filter(has_text='Author Agreement').wait_for();agreement=author.get_by_role('region',name='Author agreements');agreement.get_by_role('button',name='Accept prototype agreement').click();print('PASS EIC acceptance and author agreement',flush=True)
                open_eic();eic.locator('li.progress-current').filter(has_text='Final Editing').wait_for();form=eic.locator('form').filter(has_text='Invite final editor');form.get_by_label('Editor').select_option(label='Synthetic Editor');form.get_by_role('button',name='Send final editor invitation').click()
                editor.reload();panel=editor.get_by_role('region',name='Final editing workflow');panel.get_by_role('button',name='Accept final editor invitation').click();panel.get_by_role('button',name='Edit document (TXT)').click();online=panel.get_by_role('region',name='Online manuscript editor');assert online.get_by_label('Document text').input_value()=='Synthetic initial edit';online.get_by_label('Document text').fill('Synthetic final edit');online.get_by_role('button',name='Save Version').click();online.get_by_text('Version saved.',exact=False).wait_for();assert editor.evaluate("async () => (await (await fetch('/api/manuscripts/1',{headers:{Authorization:'Bearer '+sessionStorage.getItem('access_token')}})).json()).status")=='final_editing';online.get_by_role('button',name='Use saved draft').click();panel.get_by_text('Saved online TXT draft selected.').wait_for();form=panel.locator('form').filter(has_text='Upload final editing document');form.get_by_label('Editing comments').fill('Synthetic final');form.get_by_role('button',name='Submit final editing document').click()
                open_eic();form=eic.locator('form').filter(has_text='Review final edit');decide(form,'approve','Submit final edit review')
                open_author();panel=author.get_by_role('region',name='Final editing workflow');form=panel.locator('form').filter(has_text='Review final edits');decide(form,'approve','Submit final edit confirmation');print('PASS final editing and approvals',flush=True)
                open_eic();panel=eic.get_by_role('region',name='Formatting workflow');form=panel.locator('form').filter(has_text='Invite formatter');form.get_by_label('Formatter').select_option(label='Synthetic Formatter');form.get_by_role('button',name='Send formatter invitation').click()
                formatter=pages['formatter'];formatter.reload();panel=formatter.get_by_role('region',name='Formatting workflow');panel.get_by_role('button',name='Open manuscript').click();panel.get_by_role('button',name='Accept formatter invitation').click();panel.locator('li.progress-current').filter(has_text='Formatting').wait_for();screenshot(formatter,'step_128_27_85_synthetic_formatter_proof.png');form=panel.locator('form').filter(has_text='Upload formatted PDF');form.get_by_label('PDF file').set_input_files({'name':'proof.pdf','mimeType':'application/pdf','buffer':b'%PDF-1.4\nSynthetic proof'});form.get_by_label('Comments').fill('Synthetic proof');form.get_by_role('button',name='Submit formatted PDF').click()
                open_author();panel=author.get_by_role('region',name='Formatting workflow');form=panel.locator('form').filter(has_text='Review formatting');decide(form,'approve','Submit formatting review')
                open_eic();panel=eic.get_by_role('region',name='Formatting workflow');form=panel.locator('form').filter(has_text='Check author formatting review');decide(form,'approve','Submit formatting review');panel.get_by_role('button',name='Publish local prototype').click();panel.get_by_text('Local publication prototype',exact=False).wait_for();eic.get_by_text('Publication recorded in the local prototype.',exact=True).wait_for();timeline=eic.locator('ol[aria-label="Workflow timeline"]');
                for name in ('Submission','Initial Screening','Initial Editing','Peer Review','EIC Decision','Author Agreement','Final Editing','Formatting'):
                    timeline.locator('li.progress-completed').filter(has_text=name).first.wait_for()
                timeline.locator('li.progress-current').filter(has_text='Publication').wait_for();screenshot(eic,'step_128_27_85_synthetic_publication.png');print('PASS formatting approvals, evidence-backed timeline and local publication',flush=True)
                browser.close()
        except Exception:
            log.flush();log.seek(0);print('Synthetic server diagnostic:',log.read()[-3000:],flush=True);raise
        finally:
            for proc in reversed(processes):
                try:os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError:pass
            for proc in reversed(processes):
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()

if __name__=='__main__':run()
