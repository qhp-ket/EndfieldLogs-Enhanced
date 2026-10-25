"""Elevate only the recorder; relay bounded JSON over an authenticated local pipe.

The GUI keeps its existing stdin/stdout subprocess protocol. No shell commands,
network listener, input events or reusable credentials pass through the broker.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as w
import io
import json
from multiprocessing.connection import Client,Listener
from datetime import datetime
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time
import uuid

LIMIT=1024*1024
ENTRY='from endfield_pcap.inputlog.elevation import elevated_main; elevated_main()'


def is_admin():
    return bool(ctypes.WinDLL('shell32').IsUserAnAdmin())


class AdminProcess:
    def __init__(self,handle):
        self.handle=handle
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
        self.kernel.CloseHandle.argtypes=[w.HANDLE]

    def poll(self):
        code=w.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle,ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return None if code.value==259 else code.value

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle=None


def launch_admin(executable,arguments):
    class ExecuteInfo(ctypes.Structure):
        _fields_=[('size',w.DWORD),('mask',w.ULONG),('hwnd',w.HWND),('verb',w.LPCWSTR),
            ('file',w.LPCWSTR),('parameters',w.LPCWSTR),('directory',w.LPCWSTR),
            ('show',ctypes.c_int),('instance',w.HINSTANCE),('id_list',ctypes.c_void_p),
            ('class_name',w.LPCWSTR),('class_key',w.HKEY),('hotkey',w.DWORD),
            ('icon',w.HANDLE),('process',w.HANDLE)]
    shell=ctypes.WinDLL('shell32',use_last_error=True)
    shell.ShellExecuteExW.argtypes=[ctypes.POINTER(ExecuteInfo)]
    shell.ShellExecuteExW.restype=w.BOOL
    info=ExecuteInfo(size=ctypes.sizeof(ExecuteInfo),mask=0x40,verb='runas',file=executable,
                     parameters=subprocess.list2cmdline(arguments),show=0)
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        error=ctypes.get_last_error()
        if error==1223: raise OSError('已取消输入记录的管理员授权；其他服务不受影响')
        raise OSError(f'无法以管理员权限启动输入记录：{ctypes.WinError(error)}')
    return AdminProcess(info.process)


def send(connection,payload,lock=None):
    data=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(data)>LIMIT: raise ValueError('输入服务控制消息超过大小限制')
    if lock:
        with lock: connection.send_bytes(data)
    else: connection.send_bytes(data)


def receive(connection):
    payload=json.loads(connection.recv_bytes(LIMIT))
    if not isinstance(payload,dict): raise ValueError('输入服务控制消息格式无效')
    return payload


class PipeInput:
    def __init__(self,connection): self.connection=connection
    def __iter__(self): return self
    def __next__(self):
        try: payload=receive(self.connection)
        except (EOFError,OSError): raise StopIteration
        if payload.get('command') not in ('stop','trace'):
            raise ValueError('输入服务命令无效')
        return json.dumps(payload)+'\n'


class PipeOutput(io.TextIOBase):
    def __init__(self,connection,stream,lock):
        self.connection,self.stream,self.lock=connection,stream,lock
    def write(self,text):
        if text: send(self.connection,dict(stream=self.stream,text=text),self.lock)
        return len(text)
    def flush(self): pass


def elevated_main():
    if not is_admin(): raise RuntimeError('输入记录进程未取得管理员权限')
    connection=Client(sys.argv[1],family='AF_PIPE',authkey=bytes.fromhex(sys.argv[2]))
    original=sys.stdin,sys.stdout,sys.stderr
    try:
        config=receive(connection)
        # Accept recording settings only, never code or a process to execute.
        if set(config)-{'game_exe','log_dir','trace'}: raise ValueError('输入服务配置格式无效')
        lock=threading.Lock()
        sys.stdin=PipeInput(connection)
        sys.stdout=PipeOutput(connection,'stdout',lock)
        sys.stderr=PipeOutput(connection,'stderr',lock)
        from endfield_pcap.inputlog.worker import run
        run(config)
    finally:
        sys.stdin,sys.stdout,sys.stderr=original
        connection.close()


def relay(config):
    from endfield_pcap.inputlog.controller import worker_bootstrap
    address=rf'\\.\pipe\EndfieldLogs-Input-{uuid.uuid4().hex}'
    key=secrets.token_bytes(32)
    listener=Listener(address,family='AF_PIPE',authkey=key)
    process=None
    connection=None
    accepted=queue.Queue()
    def prepare_directory(trace):
        # Create log folders with the ordinary user's inherited permissions,
        # including when UAC uses a different administrator account.
        folder=Path(trace).parent if trace else Path(config['log_dir'])/datetime.now().strftime('%Y%m%d')
        folder.mkdir(parents=True,exist_ok=True)
    try:
        prepare_directory(config.get('trace'))
        print(json.dumps(dict(status='starting',count=0,lost=0,
                              privilege='等待输入记录管理员授权')),flush=True)
        process=launch_admin(sys.executable,['-u','-B','-c',worker_bootstrap(ENTRY),address,key.hex()])
        def accept():
            try: accepted.put(listener.accept())
            except Exception as exc: accepted.put(exc)
        threading.Thread(target=accept,name='input-pipe-connect',daemon=True).start()
        deadline=time.monotonic()+30
        while connection is None:
            try: connection=accepted.get(timeout=.1)
            except queue.Empty:
                if process.poll() is not None: raise RuntimeError('管理员输入记录进程未能启动')
                if time.monotonic()>deadline: raise TimeoutError('等待管理员输入记录进程连接超时')
        if isinstance(connection,Exception): raise connection
        send(connection,config)
        def commands():
            try:
                for line in sys.stdin:
                    payload=json.loads(line)
                    if payload.get('command') not in ('stop','trace'): continue
                    if payload['command']=='trace': prepare_directory(payload.get('path'))
                    send(connection,payload)
            except (EOFError,OSError,ValueError): pass
            finally:
                try: send(connection,dict(command='stop'))
                except OSError: pass
        threading.Thread(target=commands,name='input-pipe-control',daemon=True).start()
        try:
            while True:
                payload=receive(connection)
                text=payload.get('text')
                if payload.get('stream') not in ('stdout','stderr') or not isinstance(text,str):
                    raise ValueError('输入服务状态格式无效')
                stream=sys.stdout if payload['stream']=='stdout' else sys.stderr
                stream.write(text);stream.flush()
        except EOFError: pass
        deadline=time.monotonic()+5
        while process.poll() is None and time.monotonic()<deadline: time.sleep(.02)
        code=process.poll()
        if code: raise RuntimeError(f'输入记录进程异常退出（{code}）')
        if code is None: raise RuntimeError('输入记录进程未能结束')
    finally:
        if connection is not None and not isinstance(connection,Exception): connection.close()
        listener.close()
        if process is not None: process.close()
