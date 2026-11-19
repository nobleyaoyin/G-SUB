"""Browser regression using synthetic intercepted API responses; no database or API server."""
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
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    fixtures = [
        {"manuscript_id": 1, "title": "Synthetic draft", "abstract": "Draft abstract", "status": "draft", "created_at": "2026-01-01T00:00:00Z", "has_pdf": False},
        {"manuscript_id": 2, "title": "Synthetic revision", "abstract": "Revised abstract", "status": "revised", "created_at": "2026-01-01T00:00:00Z", "has_pdf": True},
        {"manuscript_id": 3, "title": "Historical manuscript", "abstract": "History", "status": "accepted", "created_at": "2026-01-01T00:00:00Z", "has_pdf": True},
        {"manuscript_id": 4, "title": "Synthetic submission", "abstract": "Submitted", "status": "submitted", "created_at": "2026-01-01T00:00:00Z", "has_pdf": True},
        {"manuscript_id": 5, "title": "Missing status", "abstract": "Missing data", "status": None, "created_at": "2026-01-01T00:00:00Z", "has_pdf": False},
        {"manuscript_id": 6, "title": "Synthetic initial editing", "abstract": "Synthetic", "status": "initial_editing", "created_at": "2026-01-01T00:00:00Z", "has_pdf": True},
    ]
    calls = []
    failures = set()
    with tempfile.TemporaryDirectory(prefix="gsub-progress-test-") as temp:
        with open(Path(temp) / "vite.log", "w") as log:
            process = subprocess.Popen(["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port), "--strictPort"], cwd=PROJECT / "frontend", stdout=log, stderr=log, start_new_session=True)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Vite exited before startup")
                    try:
                        with urllib.request.urlopen(origin, timeout=1):
                            break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Vite startup timed out")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.add_init_script("sessionStorage.setItem('access_token', 'synthetic-token')")

                    def api(route):
                        request = route.request
                        path = request.url.split('/api', 1)[1].split('?', 1)[0]
                        calls.append((request.method, path))
                        if request.method != "GET":
                            route.fulfill(status=403, body="Unexpected write blocked")
                            return
                        if path == '/users/me':
                            payload = {"user_id": 1, "name": "Test Author", "email": "test@example.invalid", "role": "author"}
                        elif path == '/manuscripts/my':
                            payload = fixtures
                        elif path.startswith('/manuscripts/') and path.endswith('/progress'):
                            parts = path.strip('/').split('/')
                            if len(parts) != 3 or not parts[1].isdigit():
                                route.fulfill(status=404, body='Not found')
                                return
                            mid = int(parts[1])
                            if mid in failures:
                                route.fulfill(status=503, content_type='application/json', body='{}')
                                return
                            item = next((m for m in fixtures if m['manuscript_id'] == mid), None)
                            if item is None:
                                route.fulfill(status=404, body='Not found')
                                return

                            stage_map = {
                                'draft': 'Submission',
                                'submitted': 'Initial Screening',
                                'revised': 'Peer Review',
                                'initial_editing': 'Initial Editing',
                            }
                            names = [
                                'Submission', 'Initial Screening', 'Initial Editing',
                                'Peer Review', 'EIC Decision', 'Author Agreement',
                                'Final Editing', 'Formatting', 'Publication',
                            ]
                            current_stage = stage_map.get(item['status'])
                            stages = []
                            for name in names:
                                state = 'unknown'
                                if name == current_stage:
                                    state = 'current'
                                elif item['status'] == 'draft':
                                    state = 'pending'
                                elif item['status'] == 'submitted' and name == 'Submission':
                                    state = 'completed'
                                stage = {'name': name, 'state': state}

                                if mid == 2 and name == 'Initial Editing':
                                    stage['steps'] = [
                                        {'name': 'Editor Invitation', 'state': 'completed'},
                                        {'name': 'Editor Submission', 'state': 'completed'},
                                        {'name': 'Author Approval', 'state': 'completed'},
                                        {'name': 'Editor Approval', 'state': 'current'},
                                        {'name': 'EIC Approval', 'state': 'unknown'},
                                        {'name': 'Pre-review Author Confirmation', 'state': 'unknown'},
                                    ]

                                stages.append(stage)

                            payload = {
                                'manuscript_id': mid,
                                'title': item['title'],
                                'status': item['status'],
                                'review_round': 2 if mid == 2 else 1,
                                'current_stage': current_stage,
                                'next_action': 'Check the relevant workflow panel.',
                                'stages': stages,
                            }
                        elif path == '/notifications/unread-count':
                            payload = {"unread_count": 0}
                        else:
                            payload = []
                        route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))

                    page.route('**/api/**', api)
                    page.goto(origin)
                    expect(page.get_by_role('heading', name='My Manuscripts')).to_be_visible()
                    for panel in ('Author agreements', 'Initial editing workflow', 'Final editing workflow', 'Formatting workflow'):
                        expect(page.get_by_role('region', name=panel)).to_be_visible()
                    expect(page.locator('.notification-bell')).to_be_visible()
                    card = lambda mid: page.locator(f'#manuscript-{mid}')
                    progress = lambda mid: page.get_by_role('region', name=f'Manuscript {mid} progress')
                    card(1).get_by_role('button', name='View Progress').click()
                    expect(progress(1)).to_contain_text('Synthetic draft (#1)')
                    expect(progress(1)).to_contain_text('Submission')
                    expect(progress(1)).to_contain_text('Review round: 1')
                    expect(progress(1).get_by_role('listitem').first).to_contain_text('Current')
                    expect(progress(1)).to_contain_text('Upcoming')
                    expect(card(1).get_by_role('button', name='Edit Draft')).to_be_visible()
                    card(1).get_by_role('button', name='Edit Draft').click()
                    expect(card(1).get_by_role('heading', name='Edit Draft #1')).to_be_visible()
                    card(1).get_by_role('button', name='Cancel').click()

                    card(2).get_by_role('button', name='View Progress').click()
                    expect(progress(1)).to_have_count(0)
                    expect(progress(2)).to_contain_text('Synthetic revision (#2)')
                    expect(progress(2)).to_contain_text('Review round: 2')
                    expect(progress(2)).to_contain_text('Current stage Peer Review')

                    nested = progress(2).get_by_role(
                        'list', name='Initial Editing milestones'
                    )
                    expect(nested).to_be_hidden()
                    summary = progress(2).get_by_text('Initial Editing milestones', exact=True)
                    summary.focus()
                    page.keyboard.press('Enter')
                    expect(nested).to_be_visible()
                    expect(nested.get_by_role('listitem')).to_have_count(6)

                    expected_steps = [
                        ('Editor Invitation', 'Completed'),
                        ('Editor Submission', 'Completed'),
                        ('Author Approval', 'Completed'),
                        ('Editor Approval', 'Current'),
                        ('EIC Approval', 'Status unavailable'),
                        ('Pre-review Author Confirmation', 'Status unavailable'),
                    ]

                    for index, (name, state) in enumerate(expected_steps):
                        milestone = nested.get_by_role('listitem').nth(index)
                        expect(milestone).to_contain_text(name)
                        expect(milestone).to_contain_text(state)
                    page.keyboard.press('Enter')
                    expect(nested).to_be_hidden()
                    assert 'CONFIDENTIAL REVIEWER' not in progress(2).inner_text()
                    assert 'INTERNAL SECRET' not in progress(2).inner_text()
                    assert '/private/hidden' not in progress(2).inner_text()

                    card(3).get_by_role('button', name='View Progress').click()
                    expect(progress(3)).to_contain_text('Stage unavailable')
                    expect(progress(3)).not_to_contain_text('Unknown')
                    expect(progress(3)).to_contain_text('Some stage information is unavailable')
                    card(5).get_by_role('button', name='View Progress').click()
                    expect(progress(5)).to_contain_text('Stage unavailable')
                    expect(progress(5)).to_contain_text('Review round: 1')
                    card(4).get_by_role('button', name='View Progress').click()
                    expect(progress(4)).to_contain_text('Initial Screening')
                    expect(progress(4).get_by_role('listitem').first).to_contain_text('Completed')
                    card(6).get_by_role('button', name='View Progress').click()
                    expect(progress(6)).to_contain_text('Current stage Initial Editing')
                    for width in (1280, 768, 390):
                        page.set_viewport_size({'width': width, 'height': 900})
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')

                    failures.add(2)
                    card(2).get_by_role('button', name='View Progress').click()
                    expect(progress(2).get_by_role('alert')).to_contain_text('Unable to load manuscript progress')
                    assert 'Synthetic revision (#2)' not in progress(2).inner_text()
                    failures.remove(2)
                    progress(2).get_by_role('button', name='Refresh progress').click()
                    expect(progress(2)).to_contain_text('Review round: 2')
                    card(2).get_by_role('button', name='Close Progress').click()
                    expect(progress(2)).to_have_count(0)
                    page.get_by_role('button', name='+ New Draft').click()
                    expect(page.get_by_role('heading', name='Create New Draft')).to_be_visible()
                    assert all(method == 'GET' for method, _ in calls), calls
                    assert ('GET', '/manuscripts/2/progress') in calls, calls
                    assert not any(path.startswith('/eic/manuscripts/') for _, path in calls), calls
                    print('PASS: selection, draft actions, status, round, legacy unknown, timeline, read failure/retry, switching and private-field filtering')
                    print('PASS: all intercepted API requests were read-only; no backend or database used')
                    browser.close()
            finally:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
