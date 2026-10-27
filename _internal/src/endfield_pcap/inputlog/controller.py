"""Parent ownership of input subprocess. IPC carries bounded status, never raw traffic."""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading

LOGGER = logging.getLogger(__name__)


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
        self.status = {'status':'stopped','count':0,'lost':0}
        self._lock = threading.Lock()
        self._trace = None

    def start(self, game_exe, log_dir, *, elevated=False):
        if self.running:
            return
        bootstrap = worker_bootstrap()
        cfg = dict(game_exe=str(game_exe),log_dir=str(log_dir),trace=self._trace,elevated=elevated)
        self.status = dict(status='starting',count=0,lost=0)
        env = dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
        self.process = subprocess.Popen([sys.executable,'-u','-c',bootstrap,json.dumps(cfg)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
            encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env=env)
        process = self.process
        error_tail = ''
        error_lock = threading.Lock()
        def drain_errors():
            nonlocal error_tail
            try:
                while chunk := process.stderr.read(1024):
                    with error_lock:
                        error_tail = (error_tail + chunk)[-8192:]
            except (OSError, ValueError):
                pass
            finally:
                process.stderr.close()
        errors = threading.Thread(target=drain_errors, name='input-stderr', daemon=True)
        errors.start()
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
                process.wait()
                errors.join(1)
                with error_lock:
                    error = error_tail[-1500:]
                with self._lock:
                    if self.process is process and self.status.get('status') != 'error':
                        self.status = dict(self.status,status='error' if process.returncode else 'stopped',
                                           error=error if process.returncode else '')
            except (OSError, ValueError):
                pass
            finally:
                process.stdout.close()
                process.stdin.close()
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
        process = self.process
        if not wait or process is None:
            return
        failure = None
        for action, timeout in ((None, 8), ('terminate', 3), ('kill', 1)):
            try:
                if process.poll() is not None:
                    return
                if action is not None:
                    getattr(process, action)()
                process.wait(timeout)
                return
            except (OSError, subprocess.TimeoutExpired) as exc:
                failure = exc
        LOGGER.warning('输入记录进程退出失败（PID %s）：%s', process.pid, failure)
        with self._lock:
            if self.process is process:
                self.status = dict(self.status, status='error', error='输入记录进程未能退出，请查看程序日志。')
