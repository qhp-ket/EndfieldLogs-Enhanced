"""Launch the source Qt GUI with workspace-local dependencies and settings."""
from __future__ import annotations

import argparse
import importlib
import logging
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / ".dev-gui"
_DLL_DIRECTORIES = []
_STDIO_HANDLES = []


def show_startup_error(message: str) -> None:
    log_path = PROFILE / 'logs' / 'launcher.log'
    text = f'{message}\n\n日志：{log_path}'
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, 'Endfield Logs - Enhanced GUI 启动失败', 0x10)
    elif sys.stderr is not None:
        print(text, file=sys.stderr)


def launch_detached(arguments: list[str]) -> int:
    """Keep the CMD until the windowless child has shown its GUI."""
    interpreter = Path(sys.executable)
    windowless = interpreter.with_name('pythonw.exe')
    if sys.platform == 'win32' and windowless.is_file():
        interpreter = windowless
    log_dir = PROFILE / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    command = [str(interpreter)]
    if sys.flags.isolated:
        command.append('-I')
    command.extend(['-B', str(Path(__file__).resolve()), *arguments])
    reconfigure = getattr(getattr(sys, 'stdout', None), 'reconfigure', None)
    if reconfigure is not None:
        reconfigure(encoding='utf8')
    print('正在打开 GUI，请稍候…', flush=True)
    with tempfile.TemporaryDirectory(prefix='startup-', dir=log_dir) as temporary:
        ready = Path(temporary) / 'ready'
        environment = dict(os.environ, ENDFIELD_GUI_READY_FILE=str(ready))
        with (log_dir / 'launcher-stdio.log').open('a', encoding='utf8') as output:
            process = subprocess.Popen(
                command,
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                close_fds=True, env=environment,
            )
        while not ready.is_file():
            result = process.poll()
            if result is not None:
                print('GUI 尚未打开便已退出，请查看 .dev-gui\\logs\\launcher.log。', flush=True)
                return result or 1
            time.sleep(.05)
    return 0


def notify_gui_ready() -> None:
    ready = os.environ.pop('ENDFIELD_GUI_READY_FILE', '')
    if ready:
        try:
            Path(ready).touch()
        except OSError:
            logging.getLogger('gui-launcher').warning('启动控制台已退出，GUI 继续运行。')


def bootstrap() -> None:
    sys.dont_write_bytecode = True
    os.chdir(ROOT)
    os.environ["ENDFIELD_LOGS_DATA_ROOT"] = str(ROOT / "_internal")
    os.environ["ENDFIELD_LOGS_DISABLE_UPDATE"] = "1"
    os.environ["LOCALAPPDATA"] = str(PROFILE / "local")
    os.environ["APPDATA"] = str(PROFILE / "roaming")
    sys.path.insert(0, str(ROOT / '_internal/src'))
    from endfield_pcap.runtime.environment import configure_paths
    _DLL_DIRECTORIES.extend(configure_paths(ROOT))
    log_dir = PROFILE / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    # pythonw has no Python standard streams. Give direct prints/tracebacks a
    # disk destination too; Qt/native stderr is inherited from the launcher.
    if sys.stdout is None or sys.stderr is None:
        output = (log_dir / 'launcher-stdio.log').open('a', encoding='utf8', buffering=1)
        _STDIO_HANDLES.append(output)
        if sys.stdout is None:
            sys.stdout = output
        if sys.stderr is None:
            sys.stderr = output
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_dir / "launcher.log", encoding="utf-8")],
    )


def prepare_config(game_dir: Path | None = None, ws_port: int | None = None) -> Path:
    from endfield_pcap.gui.config import AppConfig
    from endfield_pcap.gui.config import default_overlay_entries
    from endfield_pcap.gui.config import default_service_config
    from endfield_pcap.gui.config import load_app_config
    from endfield_pcap.gui.config import save_app_config

    path = PROFILE / "settings.json"
    if path.exists():
        config = load_app_config(path)
    else:
        # Write an explicit first config so the GUI never falls back to an
        # existing installation's legacy settings or enabled specialist views.
        service = default_service_config()
        service.log_dir = PROFILE / "logs/battles"
        service.debug_dir = PROFILE / "debug"
        service.rsa_key_txt = ROOT / "_internal/secrets/client_privkey.pem"
        service.name_index_path = ROOT / "_internal/jsondata/CharacterNameIndex.json"
        entries = default_overlay_entries()
        for entry in entries:
            entry.enabled = entry.source_value == "damage"
        config = AppConfig(service=service, overlays=entries)
    if game_dir is not None:
        config.service.dll_dir = game_dir.resolve()
    if ws_port is not None:
        config.service.ws_port = ws_port
    save_app_config(config, path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the source Qt GUI; no EXE build.")
    parser.add_argument("--check", action="store_true", help="Check imports and capture prerequisites without starting capture or GUI.")
    parser.add_argument('--detach', action='store_true', help='Start GUI without a console; return once its window is shown. --check remains synchronous.')
    parser.add_argument("--game-dir", type=Path, help="Save the Endfield Game directory; otherwise use the GUI first-run wizard.")
    parser.add_argument("--ws-port", type=int, help="Save an alternate localhost WebSocket port.")
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments)
    if args.ws_port is not None and not 1 <= args.ws_port <= 65535:
        parser.error("--ws-port must be between 1 and 65535")
    logger = logging.getLogger("gui-launcher")
    try:
        if args.detach and not args.check:
            return launch_detached([arg for arg in arguments if arg != '--detach'])
        bootstrap()
        for name in ("PySide6.QtWebEngineWidgets", "qfluentwidgets", "dpkt", "Crypto", "google.protobuf", "websockets", "psutil"):
            importlib.import_module(name)
        from endfield_pcap.gui.pages.settings.paths import _is_valid_game_dir
        from endfield_pcap.gui.main import run_gui
        from endfield_pcap.gui.config import load_app_config
        from endfield_pcap.capture.npcap import has_npcap

        config_path = prepare_config(args.game_dir, args.ws_port)
        config = load_app_config(config_path)
        logger.info("Python: %s", sys.executable)
        logger.info("Source GUI: %s", ROOT / "_internal/src/endfield_pcap/gui/main.py")
        logger.info("Config: %s", config_path)
        logger.info("Battle logs: %s", config.service.log_dir)
        logger.info("WebSocket: ws://127.0.0.1:%s/ws", config.service.ws_port)
        if not config.service.rsa_key_txt.is_file():
            logger.warning('缺少抓包密钥：实时服务需要先准备 _internal/secrets/client_privkey.pem；本地日志分析仍可使用。')
        if args.check:
            logger.info("GUI imports: OK")
            logger.info("Npcap DLL available: %s", has_npcap())
            logger.info("Game directory configured: %s", _is_valid_game_dir(config.service.dll_dir))
            logger.info("Endfield Logs - Enhanced GUI and damage overlay imports are ready; no capture started.")
            return 0
        if not has_npcap():
            logger.warning('未检测到 Npcap：实时抓包不可用；GUI 仍可导入和分析本地日志。')
        logger.info('GUI 默认不启动抓包；可在首页手动启动，或在设置中开启随启动抓包。')
        return run_gui(config_path=config_path, on_ready=notify_gui_ready)
    except Exception as exc:
        logger.exception("GUI startup failed")
        log_path = PROFILE / 'logs' / 'launcher.log'
        if not any(isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_path.resolve()
                   for handler in logging.getLogger().handlers):
            # Failures before bootstrap completes must also leave a traceback.
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open('a', encoding='utf8') as output:
                    output.write(traceback.format_exc() + '\n')
            except OSError:
                pass
        if not args.check:
            reason = (str(exc).splitlines() or [type(exc).__name__])[0][:180]
            show_startup_error(f'无法启动 GUI：{reason}')
        elif sys.stderr is not None:
            print("\nSee .dev-gui/logs/launcher.log. Keep _internal/python_deps installed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
