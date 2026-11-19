"""Run two independent synthetic browser workflows; no existing data roots."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]

def port():
    with socket.socket() as s: s.bind(('127.0.0.1',0));return s.getsockname()[1]
def ready(proc,url):
    for _ in range(120):
        if proc.poll() is not None: raise RuntimeError('isolated server exited')
        try:
            with urllib.request.urlopen(url,timeout=0.5): return
        except OSError: time.sleep(.1)
    raise RuntimeError('isolated server did not start')

def run(mode):
    backend,frontend=port(),port();base=f'http://127.0.0.1:{backend}';origin=f'http://127.0.0.1:{frontend}'
    if backend == frontend: raise RuntimeError('Could not reserve distinct test ports')
    env=os.environ.copy();env.update(A6_BROWSER_PORT=str(backend),PYTHONPATH=str(ROOT),PYTHON_DOTENV_DISABLED='1',PYTHONDONTWRITEBYTECODE='1',VITE_API_PROXY_TARGET=base)
    processes=[]
    with tempfile.TemporaryDirectory(prefix='gsub-a6-browser-log-') as temp:
        with (Path(temp)/'server.log').open('w+') as log:
            try:
                server=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'tests/a6_browser_fixture_server.py')],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True);processes.append(server);ready(server,base+'/health')
                vite=subprocess.Popen(['npm','run','dev','--','--host','127.0.0.1','--port',str(frontend),'--strictPort'],cwd=ROOT/'frontend',env=env,stdout=log,stderr=log,start_new_session=True);processes.append(vite);ready(vite,origin)
                with sync_playwright() as p:
                    browser=p.chromium.launch(headless=True)
                    context=browser.new_context(accept_downloads=True)
                    context.route('**/*',lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                    eic=context.new_page(); reviewer=browser.new_context(accept_downloads=True); reviewer.route('**/*',lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort());page=reviewer.new_page()
                    def login(tab,role,email,dashboard):
                        tab.goto(origin);tab.get_by_role('button',name=role,exact=True).click();tab.locator('#email').fill(email);tab.locator('#password').fill('Synthetic-Test-Password-472!');tab.get_by_role('button',name='Sign In').click();tab.get_by_text(dashboard,exact=False).first.wait_for()
                    login(eic,'Editor-in-Chief','eic@example.com','EIC Dashboard');eic.get_by_role('button',name='#3 Synthetic blind manuscript').click()
                    blind=eic.get_by_role('region',name='Blind review');blind.get_by_label('Review mode').select_option(mode);blind.get_by_role('button',name='Save review mode').click();blind.get_by_text('Not locked',exact=False).wait_for()
                    capture=os.environ.get('A6_SYNTHETIC_SCREENSHOT')
                    if capture and mode=='single_blind':
                        target=Path(capture).resolve()
                        if target.parent != (ROOT/'reports').resolve(): raise RuntimeError('Screenshot must be in reports/')
                        with target.open('xb') as output: output.write(eic.screenshot(full_page=True))
                    panel=eic.get_by_role('region',name='Reviewer invitations');panel.get_by_label('Search reviewers by name or email').fill('reviewer@example.com');panel.get_by_role('option',name='Synthetic Unique Reviewer — reviewer@example.com').wait_for(state='attached');panel.get_by_role('combobox').select_option('2');panel.get_by_role('button',name='Invite reviewer').click();panel.get_by_text('Reviewer invitation sent.').wait_for();blind.get_by_text('Mode: Single-Blind · Locked' if mode=='single_blind' else 'Mode: Double-Blind · Locked',exact=True).wait_for()
                    login(page,'Peer Reviewer','reviewer@example.com','Reviewer Dashboard')
                    page.locator('.notification-bell').click()
                    notice=page.locator('.notification-item').filter(has_text='You have a reviewer invitation.')
                    notice.get_by_role('button',name='Mark as Read').click();notice.get_by_role('button',name='Mark as Read').wait_for(state='hidden')
                    notice.get_by_role('button',name='You have a reviewer invitation.').click()
                    card=page.locator('.reviewer-card').filter(has_text='Manuscript #3');card.get_by_text('Invitation: pending').wait_for();assert 'Synthetic blind manuscript' not in card.inner_text()
                    with page.expect_response(lambda r: r.url.endswith('/api/manuscripts/3/progress')) as progress:
                        card.get_by_role('button',name='Accept review invitation').click()
                    card.get_by_text('Invitation: accepted').wait_for();card.locator('ol[aria-label="Workflow timeline"]').wait_for()
                    assert progress.value.status == 200 and 'title' not in progress.value.json()
                    with page.expect_response(lambda r: r.url.endswith('/api/manuscripts/3')) as info:
                        card.get_by_role('button',name='View manuscript details').click()
                    payload=info.value.json(); details=card.locator('[aria-label="Manuscript details"]');details.wait_for()
                    if mode=='double_blind':
                        assert 'Author ID' not in details.inner_text() and set(payload)=={'manuscript_id','review_round'}
                        assert page.evaluate("async () => (await fetch('/api/manuscripts/3/download', {headers: {Authorization: 'Bearer '+sessionStorage.getItem('access_token')}})).status")==403
                    else: assert 'Author: Synthetic Manuscript Author' in details.inner_text() and payload['author_name']=='Synthetic Manuscript Author'
                    if mode=='double_blind':
                        eic.bring_to_front();eic.evaluate("window.dispatchEvent(new Event('focus'))");panel.get_by_role('button',name='Bind reviewer document').click();panel.get_by_text('Reviewer document bound.').wait_for()
                    with page.expect_download() as event: card.get_by_role('button',name='Download Review File').click()
                    expected=b'Anonymous synthetic browser document' if mode=='double_blind' else b'%PDF-synthetic'
                    assert Path(event.value.path()).read_bytes()==expected
                    card.get_by_label('Review Comments').fill('Synthetic browser review');card.get_by_label('Recommendation').select_option('revision');card.get_by_role('button',name='Submit Review').click();page.get_by_text('Review submitted',exact=False).first.wait_for();card.get_by_text('Review already submitted.').wait_for()
                    author=browser.new_context();author.route('**/*',lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort());author_page=author.new_page()
                    login(author_page,'Author / Submitter','author@example.com','Author Dashboard')
                    author_card=author_page.locator('#manuscript-3');author_card.wait_for();author_card.get_by_role('button',name='Open manuscript').click();author_card.locator('ol[aria-label="Workflow timeline"]').wait_for()
                    assert 'reviewer@example.com' not in author_card.inner_text() and 'Synthetic Unique Reviewer' not in author_card.inner_text()
                    browser.close();print(f'PASS {mode}: EIC selection, invitation, acceptance, download and review'+(', artifact binding' if mode=='double_blind' else ''))
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
