"""Disk recording boundaries owned by the capture event loop."""
import json
from uuid import uuid4

from endfield_pcap.trace.bridge import TraceBridge, make_archive_trace_file
from endfield_pcap.trace.recording import TraceRecording


class DiskRecording:
    @property
    def recording(self):
        return getattr(self, '_disk_trace', None) is not None

    def set_recording(self, active):
        if bool(active) == self.recording:
            return (self.current_log_path, self.config.trace_file) if active else (None, None)
        if not active:
            if not isinstance(self.trace_bridge, TraceRecording) or not self.trace_bridge._closed:
                self.trace_bridge.flush_pending()
            disk, self._disk_trace = self._disk_trace, None
            try:
                if isinstance(disk, TraceRecording):
                    disk.close(finish_session=False)
                else:
                    disk.flush_pending()
            finally:
                if self.log_file is not None:
                    try:
                        self.log_file.flush()
                    finally:
                        self.log_file.close()
                        self.log_file = None
                self._write_status()
                self.status_file = None
            return None, None
        self.trace_bridge.flush_pending()
        from endfield_pcap.trace.recording import make_recording_header
        header = make_recording_header()
        path = None if getattr(self, '_recorded_once', False) else self.config.trace_file
        if self.config.trace_format == 'jsonl':
            disk = TraceRecording(lambda events: None, header, log_directory=self.config.log_dir,
                                  trace_file=path.with_suffix('.jsonl') if path else None)
        else:
            disk = TraceBridge(path or make_archive_trace_file(self.config.log_dir))
        self._disk_trace = disk
        self.config.trace_file = disk.trace_file
        self.status_file = self.config.status_file = (self.config.status_file if not getattr(self, '_recorded_once', False) else None) or disk.trace_file.with_suffix(disk.trace_file.suffix + '.status.json')
        try:
            self._open_log_file(str(uuid4()))
            for event in self._recording_context.snapshot():
                disk.handle_event(event)
                self._write_recorded_event(event)
            disk.flush_pending()
            self._recorded_once = True
            self._write_status()
            return self.current_log_path, self.config.trace_file
        except BaseException:
            self.set_recording(False)
            raise

    def _write_recorded_event(self, payload):
        if self._disk_trace is None:
            return
        self.log_file.write(json.dumps(payload, ensure_ascii=False) + '\n')
        self.log_file.flush()
        self._log_event_count += 1

    def _write_disk_events(self, events):
        if isinstance(self._disk_trace, TraceRecording):
            self._disk_trace.append_events(events)

    def _write_disk_line(self, line):
        if self.recording and not isinstance(self._disk_trace, TraceRecording):
            with self._disk_trace.trace_file.open('a', encoding='utf8', newline='') as stream:
                stream.write(line)
