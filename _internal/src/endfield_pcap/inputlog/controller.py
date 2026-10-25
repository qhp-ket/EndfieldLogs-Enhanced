"""Parent ownership of input subprocess. IPC carries bounded status, never raw traffic."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import threading


def worker_bootstrap(entry='from endfield_pcap.inputlog.worker import main; main()'):
    from endfield_pcap.runtime.paths import bundle_root
    root = bundle_root().parent
    return ('import sys; from pathlib import Path; '
        f'sys.path.insert(0,{str(root/"_internal/src")!r}); '
        'from endfield_pcap.runtime.environment import configure_paths; '
        f'_dlls=configure_paths(Path({str(root)!r})); '+entry)


class InputController:
    def __init__(self):
        self.process = None
        self.status = {'status':'stopped','count':0,'lost':0,'recent':[]}
        self._lock = threading.Lock()
        self._trace = None

    def start(self, game_exe, log_dir, *, elevated=False):
        if self.running:
            return
        bootstrap = worker_bootstrap()
        cfg = dict(game_exe=str(game_exe),log_dir=str(log_dir),trace=self._trace,elevated=elevated)
        self.status = dict(status='starting',count=0,lost=0,recent=[])
        env = dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
        self.process = subprocess.Popen([sys.executable,'-u','-c',bootstrap,json.dumps(cfg)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
            encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env=env)
        process = self.process
        def read():
            try:
                for line in process.stdout:
                    try:
                        status = json.loads(line)
                    except ValueError:
                        continue
                    with self._lock:
                        if self.process is process:
                            self.status = status
                error = process.stderr.read()[-1500:]
                process.wait()
                with self._lock:
                    if self.process is process and self.status.get('status') != 'error':
                        self.status = dict(self.status,status='error' if process.returncode else 'stopped',
                                           error=error if process.returncode else '')
            except OSError:
                pass
        threading.Thread(target=read,name='input-status',daemon=True).start()

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def snapshot(self):
        with self._lock:
            return dict(self.status)

    def command(self, **payload):
        if self.running:
            try:
                self.process.stdin.write(json.dumps(payload)+'\n')
                self.process.stdin.flush()
            except (OSError,ValueError):
                pass

    def set_trace(self,path):
        self._trace = str(path) if path else None
        self.command(command='trace',path=self._trace)

    def stop(self,wait=False):
        self.command(command='stop')
        if wait and self.running:
            try:
                self.process.wait(8)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(3)
