"""Real UI split-review workflow against isolated synthetic data."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.a6_browser_acceptance import ROOT, port, ready


def run(mode):
    backend, frontend = port(), port()
    if backend == frontend: raise RuntimeError('Could not reserve test ports')
    base = f'http://127.0.0.1:{backend}'; origin = f'http://127.0.0.1:{frontend}'
    env = os.environ.copy(); env.update(A6_BROWSER_PORT=str(backend), PYTHONPATH=str(ROOT), PYTHON_DOTENV_DISABLED='1', PYTHONDONTWRITEBYTECODE='1', VITE_API_PROXY_TARGET=base)
    processes = []
    with tempfile.TemporaryDirectory(prefix='gsub-split-browser-log-') as temp, (Path(temp)/'server.log').open('w+') as log:
        try:
            server = subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'tests/split_review_browser_fixture.py')],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True); processes.append(server); ready(server,base+'/health')
            vite = subprocess.Popen(['npm','run','dev','--','--host','127.0.0.1','--port',str(frontend),'--strictPort'],cwd=ROOT/'frontend',env=env,stdout=log,stderr=log,start_new_session=True); processes.append(vite); ready(vite,origin)
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True)
                def context():
                    c=browser.new_context(accept_downloads=True)
                    c.route('**/*',lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort()); return c
                def login(page,role,email,dashboard):
                    page.goto(origin); page.get_by_role('button',name=role,exact=True).click();page.locator('#email').fill(email);page.locator('#password').fill('Synthetic-Test-Password-472!');page.get_by_role('button',name='Sign In').click();page.get_by_text(dashboard,exact=False).first.wait_for()
                eic=context().new_page();login(eic,'Editor-in-Chief','eic@example.com','EIC Dashboard');eic.get_by_role('button',name='#3 Synthetic blind manuscript').click()
                blind=eic.get_by_role('region',name='Blind review');blind.get_by_label('Review mode').select_option(mode);blind.get_by_role('button',name='Save review mode').click();blind.get_by_text('Not locked',exact=False).wait_for()
                def reopen():
                    eic.bring_to_front(); eic.once('dialog',lambda d:d.accept());eic.get_by_role('button',name='Back to Manuscripts').click();eic.get_by_role('button',name='#3 Synthetic blind manuscript').click();eic.get_by_role('region',name='Blind review').wait_for()
                def invite(uid):
                    panel=eic.get_by_role('region',name='Reviewer invitations'); address='reviewer@example.com' if uid==2 else f'reviewer{uid}@example.com'
                    field=panel.get_by_label('Search reviewers by name or email');field.fill(address)
                    select=panel.get_by_role('combobox');select.locator(f'option[value="{uid}"]').wait_for(state='attached');select.select_option(str(uid))
                    panel.get_by_role('button',name='Invite additional reviewer' if uid==8 else 'Invite reviewer',exact=True).click();panel.get_by_text('Reviewer invitation sent.').wait_for()
                def review(uid,recommendation):
                    page=context().new_page();address='reviewer@example.com' if uid==2 else f'reviewer{uid}@example.com'
                    login(page,'Peer Reviewer',address,'Reviewer Dashboard')
                    page.locator('.notification-bell').click();notice=page.locator('.notification-item').filter(has_text='You have a reviewer invitation.');notice.get_by_role('button',name='You have a reviewer invitation.').click()
                    card=page.locator('.reviewer-card').filter(has_text='Manuscript #3');card.get_by_role('button',name='Accept review invitation').click();card.get_by_text('Invitation: accepted').wait_for()
                    if mode=='double_blind':
                        eic.bring_to_front();eic.evaluate("window.dispatchEvent(new Event('focus'))")
                        row=eic.get_by_role('region',name='Reviewer invitations').locator('li').filter(has_text=f'Reviewer #{uid}')
                        row.get_by_role('button',name='Bind reviewer document').click();eic.get_by_text('Reviewer document bound.').wait_for()
                    page.bring_to_front()
                    with page.expect_download() as download: card.get_by_role('button',name='Download Review File').click()
                    assert Path(download.value.path()).read_bytes() == (b'Anonymous synthetic browser document' if mode=='double_blind' else b'%PDF-synthetic')
                    card.get_by_label('Review Comments').fill('Synthetic review');card.get_by_label('Recommendation').select_option(recommendation);card.get_by_role('button',name='Submit Review').click();card.get_by_text('Review already submitted.').wait_for();page.close()
                invite(2);review(2,'accept');reopen();invite(7);review(7,'reject');reopen()
                summary=eic.get_by_role('region',name='Split review status');summary.get_by_text('Opposing accept and reject',exact=False).wait_for()
                invite(8);review(8,'revision');reopen()
                summary=eic.get_by_role('region',name='Split review status');summary.get_by_text('3 eligible completed reviews',exact=False).wait_for()
                text=summary.inner_text();assert all(word in text for word in ('accept','reject','revision'))
                eic.get_by_role('button',name='Record editorial decision').wait_for()
                eic.locator('.notification-bell').click();eic.get_by_text('A review was submitted for round 1.',exact=False).first.wait_for()
                browser.close();print(f'PASS {mode}: split, additional invitation, review, notification and EIC decision control')
        except Exception:
            log.flush();log.seek(0);print('Synthetic server diagnostic:',log.read()[-3000:]);raise
        finally:
            for proc in reversed(processes):
                try: os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError: pass
            for proc in reversed(processes):
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL);proc.wait()

if __name__=='__main__':
    for mode in ('single_blind','double_blind'): run(mode)
