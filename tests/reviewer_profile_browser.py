"""Reviewer profile UI with intercepted synthetic API data only."""
import json
import os
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

PROJECT = Path(__file__).resolve().parents[1]


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    state = {'profile': None, 'unavailable': False, 'writes': []}
    with tempfile.TemporaryFile() as log:
        server = subprocess.Popen(['npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=PROJECT/'frontend', stdout=log, stderr=log, start_new_session=True)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(origin, timeout=1): break
                except OSError: time.sleep(.1)
            else: raise RuntimeError('Vite startup timed out')
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True); page = browser.new_page()
                page.add_init_script("sessionStorage.setItem('access_token', 'synthetic')")
                def api(route):
                    req = route.request; path = req.url.split('/api', 1)[1].split('?', 1)[0]
                    if path == '/users/me': data = {'user_id': 1, 'name': 'Synthetic', 'email': 'synthetic@example.invalid', 'role': 'reviewer'}
                    elif path == '/notifications/unread-count': data = {'unread_count': 0}
                    elif path == '/users/me/reviewer-profile':
                        if state['unavailable']:
                            route.fulfill(status=503, content_type='application/json', body='{}'); return
                        if req.method == 'PUT':
                            state['profile'] = json.loads(req.post_data); state['writes'].append(state['profile'])
                        data = {'profile': state['profile']}
                    elif req.method != 'GET': route.fulfill(status=403, body='Blocked'); return
                    else: data = []
                    route.fulfill(status=200, content_type='application/json', body=json.dumps(data))
                page.route('**/api/**', api); page.goto(origin)
                toggle = page.get_by_role('button', name='My Professional Profile'); toggle.click()
                panel = page.get_by_role('region', name='My Professional Profile')
                expect(panel.get_by_text('Information is self-reported and is not institutionally verified.')).to_be_visible()
                title = panel.get_by_label('Professional Title'); title.focus(); assert title.evaluate('(element) => document.activeElement === element')
                title.fill('Professor'); panel.get_by_label('Institution / Affiliation').fill('Synthetic University')
                panel.get_by_label('Research Areas').fill('Systems\nSecurity')
                for width in (1280, 768, 390):
                    page.set_viewport_size({'width': width, 'height': 900})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'overflow at {width}'
                panel.get_by_role('button', name='Save profile').click()
                expect(panel.get_by_role('status')).to_have_text('Professional profile saved.')
                assert state['writes'][0]['research_areas'] == ['Systems', 'Security']
                toggle.click(); toggle.click(); expect(panel.get_by_label('Professional Title')).to_have_value('Professor')
                panel.get_by_label('Department').fill('Unsaved')
                page.once('dialog', lambda dialog: dialog.dismiss()); toggle.click(); expect(panel).to_be_visible()
                page.once('dialog', lambda dialog: dialog.accept()); toggle.click(); expect(panel).to_have_count(0)
                state['unavailable'] = True; toggle.click()
                expect(panel.get_by_role('alert')).to_contain_text('currently unavailable')
                assert len(state['writes']) == 1
                browser.close()
                print('PASS intercepted reviewer profile load, save, discard warning, unavailable state and responsive widths')
        finally:
            os.killpg(server.pid, signal.SIGTERM); server.wait(timeout=10)


if __name__ == '__main__': main()
