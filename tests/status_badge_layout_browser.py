"""Render real frontend badge/card components without a backend or database."""
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'reports' / 'manuscript_status_badge_screenshots'
LABEL = sys.argv[1] if len(sys.argv) > 1 else 'after'
if LABEL not in ('before', 'after'):
    raise ValueError('Expected before or after')

with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
server = subprocess.Popen(['npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=ROOT/'frontend', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    origin = f'http://127.0.0.1:{port}'
    for _ in range(100):
        try:
            with urllib.request.urlopen(origin, timeout=1): break
        except OSError: time.sleep(.1)
    else: raise RuntimeError('Local frontend did not start')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(origin)
        page.evaluate('''async () => {
          const React = await import('/node_modules/.vite/deps/react.js');
          const ReactDOM = await import('/node_modules/.vite/deps/react-dom_client.js');
          const {default:Badge} = await import('/src/StatusBadge.jsx');
          const {default:AuthorOverview} = await import('/src/AuthorOverview.jsx');
          const {default:ReviewerCard} = await import('/src/ReviewerManuscriptCard.jsx');
          const {default:RoleOverview} = await import('/src/RoleOverview.jsx');
          await Promise.all(['/src/AuthorDashboard.css','/src/EditorDashboard.css','/src/ReviewerDashboard.css','/src/EICDashboard.css','/src/FormattingPanel.css'].map(path=>import(path)));
          const h=(React.createElement || React.default.createElement), statuses=['draft','submitted','initial_screening','initial_scan_passed','initial_editing','ready_for_peer_review','revision_required','revised','eic_decision_pending','awaiting_author_agreement','final_editing','formatting','accepted','published'];
          const title='Synthetic exceptionally long manuscript title '+('longunbrokenmanuscriptword'.repeat(4));
          const item={manuscript_id:42,assignment_id:7,title,manuscript_title:title,status:'draft',invitation_status:'accepted',manuscript_status:'ready_for_peer_review',review_round:1};
          document.body.innerHTML='<main id="badge-root" style="padding:16px;box-sizing:border-box"></main>';
          const root=(ReactDOM.createRoot || ReactDOM.default.createRoot)(document.getElementById('badge-root'));
          root.render(h('div',null,
            h('h2',null,'Author dashboard'),h(AuthorOverview,{manuscripts:[item],loading:false,onOpen:()=>{},onNavigate:()=>{}}),
            h('h2',null,'Author manuscript card'),h('div',{className:'manuscript-card'},h('div',{className:'manuscript-card-top'},h('h3',null,title),h(Badge,{status:'draft'}))),
            h('h2',null,'Reviewer manuscript card'),h(ReviewerCard,{assignment:item,onOpen:()=>{}}),
            h('h2',null,'Reviewer detail header'),h('div',{className:'reviewer-card-top'},h('h3',null,title),h('span',{className:'reviewer-status assigned'},'Assigned')),
            h('h2',null,'Editor manuscript card'),h('div',{className:'editor-card'},h('div',{className:'editor-card-top'},h('h3',null,title),h(Badge,{status:'awaiting_author_agreement'}))),
            h('h2',null,'Formatter manuscript header'),h('div',{className:'formatter-manuscript-header'},h('div',null,h('h3',null,title)),h('span',{className:'formatter-status'},'Awaiting author agreement')),
            ...['Reviewer','Editor','EIC','Formatter'].map(label=>h('div',{key:label},h('h2',null,label+' overview'),h(RoleOverview,{label,items:[item],loading:false,hideStatistics:true,onOpen:()=>{},onNavigate:()=>{}}))),
            h('h2',null,'EIC detail header'),h('div',{className:'eic-manuscript-heading'},h('div',null,h('h2',null,title)),h('span',{className:'eic-status-badge'},'Awaiting author agreement')),
            h('h2',null,'Supported status labels'),...statuses.map(status=>h('div',{key:status,className:'manuscript-card-top',style:{maxWidth:'320px',margin:'10px 0'}},h('h3',null,title),h(Badge,{status})))));
        }''')
        page.wait_for_selector('.workflow-status-badge')
        results = {}
        for width, height in ((1440, 900), (768, 1024), (390, 844)):
            page.set_viewport_size({'width': width, 'height': height})
            page.screenshot(path=str(OUTPUT / f'{LABEL}-{width}.png'), full_page=True)
            results[width] = page.evaluate('''() => ({
              pageOverflow: document.documentElement.scrollWidth > innerWidth,
              editorStackGap: (()=>{const header=document.querySelector('.editor-card-top');const title=header.firstElementChild.getBoundingClientRect();const badge=header.lastElementChild.getBoundingClientRect();return badge.top>=title.bottom ? badge.top-title.bottom : 0;})(),
              badges: [...document.querySelectorAll('.workflow-status-badge,.eic-status-badge,.reviewer-status,.formatter-status')].map(el=>{
                const range=document.createRange(); range.selectNodeContents(el);
                const rect=el.getBoundingClientRect();
                return {label:el.innerText, lines:range.getClientRects().length,
                  clipped:el.scrollWidth>el.clientWidth+1 || rect.left < -1 || rect.right > innerWidth+1,
                  whiteSpace:getComputedStyle(el).whiteSpace, flexShrink:getComputedStyle(el).flexShrink};
              })
            })''')
        (OUTPUT / f'{LABEL}-measurements.json').write_text(json.dumps(results, indent=2))
        if LABEL == 'after':
            assert all(not result['pageOverflow'] and result['editorStackGap'] <= 32 and all(b['lines']==1 and not b['clipped'] for b in result['badges']) for result in results.values())
        print(f'{LABEL}: rendered synthetic component fixtures at 1440, 768, 390; screenshots and measurements saved')
        browser.close()
finally:
    server.terminate()
    server.wait(timeout=10)
