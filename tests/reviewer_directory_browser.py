"""Browser search/selection with every API intercepted; no database."""
import json
import os
import signal
import socket
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

PROJECT = Path(__file__).resolve().parents[1]


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    manuscript = {'manuscript_id': 4, 'title': 'Synthetic', 'status': 'ready_for_peer_review', 'review_round': 1, 'author': 'Author', 'abstract': 'Synthetic'}
    overview = {'manuscript': manuscript, 'review_progress': {'completed_distinct': 0, 'required': 2, 'policy': 'two_reviewers', 'can_decide': False}, 'submissions': [], 'decisions': [], 'final_invitations': [], 'final_workflow_submissions': [], 'scans': [], 'invitations': [], 'confirmations': [], 'assignments': [], 'author_agreement': None, 'final_submissions': []}
    writes = []
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
                    req = route.request; parsed = urllib.parse.urlparse(req.url); path = parsed.path.split('/api', 1)[1]
                    if path == '/users/me': data = {'user_id': 1, 'name': 'Synthetic', 'email': 'synthetic@example.invalid', 'role': 'eic'}
                    elif path == '/manuscripts/': data = [manuscript]
                    elif path == '/eic/manuscripts/4/overview': data = overview
                    elif path == '/formatting/manuscripts/4': data = {'manuscript_id': 4, 'title': 'Synthetic', 'status': 'ready_for_peer_review', 'invitations': [], 'submissions': [], 'publication': None}
                    elif path == '/notifications/unread-count': data = {'unread_count': 0}
                    elif path.endswith('/summary'): data = {'decision_progress': overview['review_progress']}
                    elif path.endswith('/reviewer-directory'):
                        query = urllib.parse.parse_qs(parsed.query).get('q', [''])[0]
                        data = [] if query == 'none' else [{'reviewer_id': 5, 'name': 'Synthetic Reviewer', 'email': 'reviewer@example.invalid', 'selectable': True, 'invitation_status': None, 'assignment_status': None, 'profile': {'professional_title': 'Professor', 'institution': 'Synthetic University', 'department': None, 'research_areas': ['Systems'], 'expertise': ['Security'], 'provenance': 'self_reported'}}]
                    elif path == '/assignments/' and req.method == 'POST':
                        writes.append(json.loads(req.post_data)); data = {}
                    elif req.method != 'GET': route.fulfill(status=403, body='Blocked'); return
                    else: data = []
                    route.fulfill(status=200, content_type='application/json', body=json.dumps(data))
                page.route('**/api/**', api); page.goto(origin)
                page.get_by_role('button', name='#4 Synthetic', exact=False).click()
                panel = page.get_by_role('region', name='Reviewer invitations')
                search = panel.get_by_label('Search reviewers by name or email')
                search.fill('none'); expect(panel.get_by_text('No matching reviewers.')).to_be_visible()
                search.fill('reviewer'); option = panel.get_by_role('option', name='Synthetic Reviewer — Professor — Synthetic University — reviewer@example.invalid'); expect(option).to_be_attached()
                select = panel.get_by_role('combobox'); select.focus(); assert select.evaluate('(element) => document.activeElement === element')
                page.keyboard.press('ArrowDown'); page.keyboard.press('Enter')
                if select.input_value() != '5': select.select_option('5')  # Native menu behavior varies by platform.
                expect(panel.get_by_text('self-reported; not verified', exact=False)).to_be_visible()
                expect(panel.get_by_text('Systems', exact=True)).to_be_visible()
                expect(panel.get_by_text('Not provided', exact=True)).to_be_visible()
                for width in (1280, 768, 390):
                    page.set_viewport_size({'width': width, 'height': 900})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'overflow at {width}'
                panel.get_by_role('button', name='Invite reviewer').click()
                expect(panel.get_by_role('status')).to_contain_text('Reviewer invitation sent.')
                assert writes == [{'manuscript_id': 4, 'reviewer_id': 5, 'review_round': 1}]
                browser.close()
                print('PASS intercepted reviewer search, empty state, keyboard focus, selection, invitation and responsive widths')
        finally:
            os.killpg(server.pid, signal.SIGTERM); server.wait(timeout=10)


if __name__ == '__main__': main()
