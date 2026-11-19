"""End-to-end editor acceptance on synthetic temporary data and localhost only."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); return sock.getsockname()[1]

def ready(proc, url):
    for _ in range(120):
        if proc.poll() is not None: raise RuntimeError('Synthetic server exited')
        try:
            with urllib.request.urlopen(url, timeout=.5): return
        except OSError: time.sleep(.1)
    raise RuntimeError('Synthetic server did not start')

def main():
    back, front = port(), port()
    if back == front: raise RuntimeError('Could not reserve ports')
    base = f'http://127.0.0.1:{back}'; origin = f'http://127.0.0.1:{front}'
    env = os.environ.copy(); env.update(EDITOR_BROWSER_PORT=str(back), PYTHONPATH=str(ROOT), PYTHON_DOTENV_DISABLED='1', PYTHONDONTWRITEBYTECODE='1', VITE_API_PROXY_TARGET=base)
    processes = []
    with tempfile.TemporaryDirectory(prefix='gsub-editor-browser-log-') as temp, (Path(temp)/'log').open('w+') as log:
        try:
            server = subprocess.Popen([str(ROOT/'.venv/bin/python'), str(ROOT/'tests/online_editor_browser_fixture.py')], cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True); processes.append(server); ready(server, base+'/health')
            vite = subprocess.Popen(['npm','run','dev','--','--host','127.0.0.1','--port',str(front),'--strictPort'], cwd=ROOT/'frontend', env=env, stdout=log, stderr=log, start_new_session=True); processes.append(vite); ready(vite,origin)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(accept_downloads=True)
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                page = context.new_page(); page.goto(origin)
                assert page.title() == 'G-SUB | Manuscript Submission'
                assert page.get_by_role('heading', name='G-SUB.').count() == 1
                page.get_by_role('button', name='Author / Submitter', exact=True).click()
                page.locator('#email').fill('author@example.com'); page.locator('#password').fill('Synthetic-Test-Password-472!')
                page.get_by_role('button',name='Sign In').click(); page.get_by_text('Author Dashboard',exact=False).first.wait_for()
                card=page.locator('#manuscript-80'); card.get_by_role('button',name='Open manuscript').click()
                card.get_by_role('button',name='Edit document (TXT)').click()
                editor=card.get_by_role('region',name='Online manuscript editor'); field=editor.get_by_label('Document text')
                assert field.input_value() == 'Synthetic original text'
                field.fill('Synthetic edited version')
                with page.expect_response(lambda response: response.url.endswith('/online-text') and response.request.method == 'POST') as save:
                    editor.get_by_role('button',name='Save Version').click()
                assert save.value.status == 200, f'Editor save returned {save.value.status}: {save.value.text()}'
                try: editor.get_by_text('Version saved.',exact=False).wait_for(timeout=5000)
                except Exception:
                    print('Editor display after save:', editor.inner_text()); raise
                screenshot=os.environ.get('EDITOR_SYNTHETIC_SCREENSHOT')
                if screenshot:
                    editor.get_by_text('Version History').click()
                    target=Path(screenshot).resolve()
                    if target.parent != (ROOT/'reports').resolve(): raise RuntimeError('Screenshot must be in reports')
                    with target.open('xb') as out: out.write(page.screenshot(full_page=True))
                editor.get_by_role('button',name='Cancel').click(); card.get_by_role('button',name='Edit document (TXT)').click()
                editor=card.get_by_role('region',name='Online manuscript editor'); field=editor.get_by_label('Document text')
                assert field.input_value() == 'Synthetic edited version'
                editor.get_by_text('Version History').click()
                with page.expect_download() as event: editor.get_by_role('button',name='Download').first.click()
                assert Path(event.value.path()).read_bytes() == b'Synthetic edited version'
                result=page.evaluate("""async () => { const h={Authorization:'Bearer '+sessionStorage.getItem('access_token')};
                  const original=await fetch('/api/manuscripts/80/versions/original.txt',{headers:h});
                  const m=await fetch('/api/manuscripts/80',{headers:h}); return {bytes:await original.text(), status:(await m.json()).status}; }""")
                assert result == {'bytes':'Synthetic original text','status':'draft'}
                field.fill('Unsaved synthetic change'); page.once('dialog',lambda dialog: dialog.dismiss())
                card.get_by_role('button',name='Back to Manuscripts').click(); assert field.input_value() == 'Unsaved synthetic change'
                stale=page.evaluate("""async () => {const h={Authorization:'Bearer '+sessionStorage.getItem('access_token'),'Content-Type':'application/json'};
                  const v=await (await fetch('/api/manuscripts/80/online-text',{headers:h})).json();
                  return (await fetch('/api/manuscripts/80/online-text',{method:'POST',headers:h,body:JSON.stringify({content:'Another synthetic edit',expected_version:v.version})})).status;}""")
                assert stale == 200
                editor.get_by_role('button',name='Save Version').click(); editor.get_by_role('alert').get_by_text('Document changed',exact=False).wait_for()
                other=browser.new_context();other.route('**/*',lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                reviewer=other.new_page();reviewer.goto(origin);reviewer.get_by_role('button',name='Peer Reviewer',exact=True).click()
                reviewer.locator('#email').fill('reviewer@example.com');reviewer.locator('#password').fill('Synthetic-Test-Password-472!');reviewer.get_by_role('button',name='Sign In').click();reviewer.get_by_text('Reviewer Dashboard',exact=False).first.wait_for()
                denial=reviewer.evaluate("async () => (await fetch('/api/manuscripts/80/online-text',{headers:{Authorization:'Bearer '+sessionStorage.getItem('access_token')}})).status")
                assert denial == 404
                browser.close(); print('PASS synthetic author TXT edit, history, original, warning, stale conflict and reviewer denial')
        except Exception:
            log.flush(); log.seek(0); print('Synthetic server diagnostic:',log.read()[-3000:]); raise
        finally:
            for proc in reversed(processes):
                try: os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError: pass
            for proc in reversed(processes):
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL); proc.wait()

if __name__ == '__main__': main()
