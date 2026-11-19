"""Exercise agreement synchronization with a disposable backend and synthetic fixtures."""
import json
import re
import os
import signal
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

PROJECT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_ready(process, url):
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError('Temporary server exited')
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except OSError:
            time.sleep(.1)
    raise RuntimeError('Temporary server startup timeout')


def prepare_pending(root, fixture):
    """Seed only the disposable fixture DB; do not exercise EIC Accept."""
    path = root / 'browser.sqlite'
    if not root.name.startswith('reviewer-e2e-') or not path.is_file():
        raise RuntimeError('Refusing a non-temporary fixture database')
    result = {}
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        for label in ('round1', 'pdf', 'docx', 'doc', 'legacy'):
            mid = fixture['assignments'][label]['manuscript_id']
            round_no = fixture['assignments'][label]['round']
            db.execute("UPDATE manuscripts SET status='awaiting_author_agreement' WHERE manuscript_id=?", (mid,))
            decision = db.execute("INSERT INTO eic_decisions (manuscript_id, eic_id, review_round, decision, comments, decided_at) VALUES (?, ?, ?, 'accept', 'Synthetic prior decision', datetime('now'))", (mid, fixture['user_ids']['eic'], round_no)).lastrowid
            aid = db.execute("INSERT INTO author_agreements (manuscript_id, decision_id, author_id, agreement_version, agreement_text, status, created_at) VALUES (?, ?, ?, 'placeholder-v1', 'Synthetic prototype agreement', 'pending', datetime('now'))", (mid, decision, fixture['user_ids']['author'])).lastrowid
            result[label] = {'manuscript_id': mid, 'agreement_id': aid}
        db.commit()
    return result


def main():
    with tempfile.TemporaryDirectory(prefix='reviewer-e2e-') as temporary:
        root = Path(temporary).resolve()
        backend, frontend = free_port(), free_port()
        if backend == frontend:
            raise RuntimeError('Port collision')
        base, origin = f'http://127.0.0.1:{backend}', f'http://127.0.0.1:{frontend}'
        env = os.environ.copy()
        env.update(REVIEWER_E2E_ROOT=str(root), REVIEWER_E2E_BACKEND_PORT=str(backend), REVIEWER_E2E_ORIGIN=origin, PYTHONPATH=str(PROJECT), VITE_API_PROXY_TARGET=base)
        processes = []
        with (root / 'server.log').open('w+') as log:
            try:
                server = subprocess.Popen([str(PROJECT / '.venv/bin/python'), str(PROJECT / 'tests/reviewer_browser_server.py')], cwd=PROJECT, env=env, stdout=log, stderr=log, start_new_session=True)
                processes.append(server)
                wait_ready(server, base + '/health')
                fixture = json.loads((root / 'fixtures.json').read_text())
                pending = prepare_pending(root, fixture)
                vite = subprocess.Popen(['npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(frontend), '--strictPort'], cwd=PROJECT / 'frontend', env=env, stdout=log, stderr=log, start_new_session=True)
                processes.append(vite)
                wait_ready(vite, origin)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context()
                    page = context.new_page()
                    page.goto(origin)

                    # Select Author before accessing the login form.
                    page.get_by_role(
                        'button', name=re.compile('author', re.I)
                    ).click()

                    # Wait until the role-specific login form is visible.
                    expect(page.locator('#email')).to_be_visible()
                    expect(page.locator('#password')).to_be_visible()

                    page.locator('#email').fill('author@example.com')
                    page.locator('#password').fill(fixture['password'])
                    page.get_by_role('button', name='Sign In').click()
                    def open_case(label):
                        mid = pending[label]["manuscript_id"]
                        card = page.locator(f"#manuscript-{mid}")

                        card.get_by_role(
                            "button", name="Open manuscript"
                        ).click()

                        wizard = page.get_by_role(
                            "region", name="Manuscript workflow wizard"
                        )
                        expect(wizard).to_be_visible()

                        wizard.get_by_role(
                            "button", name="Author Agreement"
                        ).click()

                        agreements = page.get_by_role(
                            "region", name="Author agreements"
                        )
                        expect(agreements.locator("article")).to_have_count(1)

                        expect(
                            agreements.get_by_role(
                                "heading",
                                name=f"Fixture {label}",
                                exact=True
                            )
                        ).to_be_visible()

                        return agreements, wizard

                    def open_final(wizard):
                        wizard.get_by_role(
                            "button", name="Final Editing"
                        ).click()

                        return page.get_by_role(
                            "region", name="Final editing workflow"
                        )

                    def agreement(agreements, label):
                        mid = pending[label]["manuscript_id"]
                        return agreements.locator("article").filter(
                            has=page.get_by_role(
                                "heading",
                                name=f"Fixture {label}",
                                exact=True
                            )
                        )

                    def manuscript(label):
                        return page.locator(
                            f"#manuscript-{pending[label]['manuscript_id']}"
                        )

                    def final(finals, label):
                        mid = pending[label]["manuscript_id"]
                        return finals.locator("article").filter(
                            has=page.get_by_role(
                                "heading",
                                name=f"#{mid} Fixture {label}",
                                exact=True
                            )
                        )

                    def close_case():
                        page.get_by_role(
                            "button", name="Back to Manuscripts"
                        ).click()

                        expect(
                            page.get_by_role(
                                "heading", name="My Manuscripts"
                            )
                        ).to_be_visible()

                    # Round 1: Accept and verify duplicate response rejection.
                    agreements, wizard = open_case("round1")
                    item = agreement(agreements, "round1")

                    # The FinalEditingPanel intentionally returns null
                    # when there are no items, errors, or messages.
                    # Verify that no final-editing article exists instead.
                    finals = open_final(wizard)
                    assert finals.count() == 0

                    wizard.get_by_role(
                        "button", name="Author Agreement"
                    ).click()

                    item = agreement(agreements, "round1")
                    item.get_by_role(
                        "button", name="Accept Agreement"
                    ).click()

                    expect(item).to_contain_text("accepted")
                    expect(manuscript("round1")).to_contain_text("final editing")

                    finals = open_final(wizard)
                    expect(finals).to_contain_text(
                        "EIC: invite a final editor."
                    )

                    assert item.get_by_role(
                        "button", name="Accept Agreement"
                    ).count() == 0

                    repeat = context.request.post(
                        base + f"/agreements/{pending['round1']['agreement_id']}/respond",
                        headers={
                            "Authorization": "Bearer " + fixture["tokens"]["author"]
                        },
                        data={
                            "decision": "accept",
                            "agreement_version": "placeholder-v1"
                        }
                    )
                    assert repeat.status == 409, repeat.status
                    print("PASS round1: accepted, final workflow refreshed, duplicate rejected")
                    close_case()

                    # PDF: Decline and verify final editing remains on hold.
                    agreements, wizard = open_case("pdf")
                    item = agreement(agreements, "pdf")

                    with page.expect_response(
                        lambda r: "/api/final-workflow/my" in r.url
                        and r.request.method == "GET"
                    ) as final_refresh:
                        item.get_by_role(
                            "button", name="Decline Agreement"
                        ).click()

                    assert final_refresh.value.ok
                    expect(item).to_contain_text("declined")
                    expect(item).to_contain_text("Final editing is on hold")
                    expect(manuscript("pdf")).to_contain_text(
                        "author agreement declined"
                    )

                    finals = open_final(wizard)
                    assert final(finals, "pdf").count() == 0
                    print("PASS pdf: declined and final editing held")
                    close_case()

                    # DOCX: Accept succeeds even when final-panel refresh fails.
                    agreements, wizard = open_case("docx")
                    item = agreement(agreements, "docx")

                    page.route(
                        "**/api/final-workflow/my",
                        lambda route: route.fulfill(
                            status=503,
                            content_type="application/json",
                            body="{}"
                        )
                    )

                    item.get_by_role(
                        "button", name="Accept Agreement"
                    ).click()

                    expect(item).to_contain_text("accepted")
                    expect(agreements.get_by_role("alert")).to_contain_text(
                        "Response saved, but refresh failed"
                    )
                    expect(agreements.get_by_role("alert")).to_contain_text(
                        "do not submit the response again"
                    )
                    assert item.get_by_role(
                        "button", name="Accept Agreement"
                    ).count() == 0
                    expect(manuscript("docx")).to_contain_text("final editing")

                    page.unroute("**/api/final-workflow/my")

                    # Return to the manuscript list and reopen the same
                    # manuscript. This remounts FinalEditingPanel and
                    # triggers its real initial data-loading effect.
                    close_case()

                    agreements, wizard = open_case("docx")
                    finals = open_final(wizard)

                    expect(final(finals, "docx")).to_contain_text(
                        "EIC: invite a final editor."
                    )

                    print(
                        "PASS docx: saved response survives failed refresh "
                        "and final editing recovers after reopening"
                    )
                    close_case()

                    # DOC: Accept succeeds even when manuscript refresh fails.
                    agreements, wizard = open_case("doc")
                    item = agreement(agreements, "doc")

                    page.route(
                        "**/api/manuscripts/my",
                        lambda route: route.fulfill(
                            status=503,
                            content_type="application/json",
                            body="{}"
                        )
                    )

                    item.get_by_role(
                        "button", name="Accept Agreement"
                    ).click()

                    expect(item).to_contain_text("accepted")
                    expect(agreements.get_by_role("alert")).to_contain_text(
                        "Response saved, but refresh failed"
                    )

                    finals = open_final(wizard)
                    expect(final(finals, "doc")).to_contain_text(
                        "EIC: invite a final editor."
                    )
                    assert item.get_by_role(
                        "button", name="Accept Agreement"
                    ).count() == 0

                    page.unroute("**/api/manuscripts/my")
                    print("PASS doc: saved response survives failed manuscript refresh")
                    close_case()

                    # Legacy: Failed POST must not appear as a saved response.
                    agreements, wizard = open_case("legacy")
                    item = agreement(agreements, "legacy")

                    page.route(
                        f"**/api/agreements/{pending['legacy']['agreement_id']}/respond",
                        lambda route: route.fulfill(
                            status=500,
                            content_type="application/json",
                            body='{"detail":"Synthetic response failure"}'
                        )
                    )

                    item.get_by_role(
                        "button", name="Accept Agreement"
                    ).click()

                    expect(agreements.get_by_role("alert")).to_contain_text(
                        "Could not confirm the agreement response"
                    )
                    expect(item).to_contain_text("pending")
                    assert item.get_by_role(
                        "button", name="Accept Agreement"
                    ).count() == 1

                    print("PASS legacy: failed POST remains pending")
                    page.unroute(
                        f"**/api/agreements/{pending['legacy']['agreement_id']}/respond"
                    )

                    # A saved decline remains visible when agreement-list refresh fails.
                    page.route(
                        "**/api/agreements/my",
                        lambda route: route.fulfill(
                            status=503,
                            content_type="application/json",
                            body="{}"
                        )
                    )

                    item.get_by_role(
                        "button", name="Decline Agreement"
                    ).click()

                    expect(item).to_contain_text("declined")
                    expect(agreements.get_by_role("alert")).to_contain_text(
                        "Response saved, but refresh failed"
                    )
                    assert item.get_by_role(
                        "button", name="Decline Agreement"
                    ).count() == 0

                    page.unroute("**/api/agreements/my")

                    # Reopen the manuscript to remount the agreement panel
                    # and verify that the saved decline persists.
                    close_case()

                    agreements, wizard = open_case("legacy")

                    item = agreements.locator("article").filter(
                        has=page.get_by_role(
                            "heading",
                            name="Fixture legacy",
                            exact=True
                        )
                    )

                    expect(item).to_contain_text("declined")
                    assert item.get_by_role(
                        "button", name="Decline Agreement"
                    ).count() == 0

                    print(
                        "PASS legacy: saved decline survives failed "
                        "agreement refresh and reopening"
                    )

                    close_case()
                    browser.close()
            finally:
                for process in reversed(processes):
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                for process in reversed(processes):
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()


if __name__ == '__main__':
    main()
