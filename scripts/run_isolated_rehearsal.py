"""Start a disposable, localhost-only G-SUB rehearsal. Never uses a supplied data root."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_ready(process, url):
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError('A local rehearsal server exited during startup')
        try:
            with urllib.request.urlopen(url, timeout=.5): return
        except OSError:
            time.sleep(.1)
    raise RuntimeError('A local rehearsal server did not become ready')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Start, check and stop without displaying credentials')
    args=parser.parse_args()
    backend,frontend=free_port(),free_port()
    if backend==frontend: raise RuntimeError('Could not allocate distinct local ports')
    password=secrets.token_urlsafe(24)+'Aa1!'
    processes=[]
    with tempfile.TemporaryDirectory(prefix='gsub-rehearsal-') as tmp:
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'), 'PYTHONPATH':str(ROOT),
             'PYTHON_DOTENV_DISABLED':'1', 'PYTHONDONTWRITEBYTECODE':'1',
             'REHEARSAL_ROOT':str(Path(tmp).resolve()), 'REHEARSAL_PORT':str(backend),
             'REHEARSAL_PASSWORD':password, 'VITE_API_PROXY_TARGET':f'http://127.0.0.1:{backend}'}
        if os.environ.get('TMPDIR'): env['TMPDIR']=os.environ['TMPDIR']
        try:
            backend_process=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'tests/five_role_rehearsal_server.py')],cwd=ROOT,env=env,start_new_session=True)
            processes.append(backend_process);wait_ready(backend_process,f'http://127.0.0.1:{backend}/health')
            frontend_process=subprocess.Popen(['npm','run','dev','--','--host','127.0.0.1','--port',str(frontend),'--strictPort'],cwd=ROOT/'frontend',env=env,start_new_session=True)
            processes.append(frontend_process);wait_ready(frontend_process,f'http://127.0.0.1:{frontend}')
            print(f'Isolated G-SUB rehearsal ready at http://127.0.0.1:{frontend}',flush=True)
            if args.check:
                for name,role in (('author','author'),('editor','editor'),('eic','eic'),('reviewer','reviewer'),('formatter','formatter')):
                    body=json.dumps({'email':f'{name}@example.com','password':password}).encode()
                    request=urllib.request.Request(f'http://127.0.0.1:{backend}/users/login',data=body,headers={'Content-Type':'application/json'},method='POST')
                    with urllib.request.urlopen(request,timeout=5) as response: token=json.load(response)['access_token']
                    request=urllib.request.Request(f'http://127.0.0.1:{backend}/users/me',headers={'Authorization':f'Bearer {token}'})
                    with urllib.request.urlopen(request,timeout=5) as response: user=json.load(response)
                    if user['role']!=role: raise RuntimeError('Synthetic role check failed')
                print('Synthetic authentication verified for all five roles.',flush=True)
            else:
                print('Synthetic accounts: author, editor, eic, reviewer, reviewer2, reviewer3, formatter at example.com.',flush=True)
                print(f'Temporary synthetic password: {password}',flush=True)
                print('Press Ctrl-C to stop. The temporary database and files will be removed.',flush=True)
                while all(proc.poll() is None for proc in processes): time.sleep(.5)
                raise RuntimeError('A local rehearsal server exited')
        except KeyboardInterrupt:
            pass
        finally:
            for proc in reversed(processes):
                try: os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError: pass
            for proc in reversed(processes):
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL);proc.wait()


if __name__=='__main__': main()
