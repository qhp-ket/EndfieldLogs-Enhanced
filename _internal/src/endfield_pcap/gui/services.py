"""Composition of optional services, separate from capture actions and analysis."""
from __future__ import annotations
import logging
from PySide6.QtCore import QTimer
from qfluentwidgets import InfoBar
from endfield_pcap.settings import save_app_config
from endfield_pcap.inputlog.controller import InputController
from endfield_pcap.vision.controller import VisionController


class IndependentServices:
    def _game_executable(self):
        return self.app_config.service.dll_dir/self.app_config.service.game_exe

    def _init_independent_services(self):
        self.input_controller=InputController()
        self.vision_controller=VisionController(self._game_executable(),self.app_config.vision_settings,self)
        self._independent_subscriptions=frozenset()
        self._vision_preview_active=False
        self._input_error=None
        self._vision_session=None

    def _set_analysis_requirements(self,subscriptions):
        self._independent_subscriptions=subscriptions
        self.service_controller.set_analysis_streams(frozenset(subscriptions & {'analysis_snapshot','analysis_summary'}))
        self.vision_controller.game_exe=self._game_executable()
        self.vision_controller.set_enabled('combo_snapshot' in subscriptions or self._vision_preview_active)

    def _bind_independent_services(self):
        self.home_page.input_service_btn.clicked.connect(self._toggle_input_recording)
        self.home_page.input_settings_btn.clicked.connect(self._show_input_settings)
        self.home_page.vision_overlays_btn.clicked.connect(lambda: self.switchTo(self.overlay_page))
        if hasattr(self.overlay_page,'vision_settings_btn'):
            self.overlay_page.vision_settings_btn.clicked.connect(self._show_vision_settings)
        if self.app_config.start_input_recording_on_launch:
            QTimer.singleShot(0,self._start_input_recording)

    def _start_input_recording(self):
        try:
            self.input_controller.start(self._game_executable(),self.app_config.service.log_dir,elevated=True)
        except Exception as exc:
            InfoBar.error(title='输入记录不可用',content=str(exc),parent=self,duration=8000)
            self.app_config.input_recording_enabled=False

    def _toggle_input_recording(self):
        if self.input_controller.running:
            self.input_controller.stop()
            self.app_config.input_recording_enabled=False
        else:
            self._start_input_recording()
            self.app_config.input_recording_enabled=self.input_controller.running
        save_app_config(self.app_config,self.config_path)

    def _drain_independent_services(self):
        if self.current_session_id!=self._vision_session:
            self._vision_session=self.current_session_id
            self.vision_controller.set_identity([],self.current_session_id)
        state=self.input_controller.snapshot()
        status=state.get('status','stopped')
        failure = state.get('error') if status == 'error' else None
        if failure and failure != self._input_error:
            logging.getLogger(__name__).error('输入记录故障：%s',failure)
        self._input_error = failure
        visual=self.vision_controller.take_snapshot()
        if visual is not None:
            self.overlay_manager.apply_combo_snapshot(visual)
        if not self.home_page.isVisible():return
        title={'stopped':'已停止','starting':'正在启动…','recording':'正在记录游戏前台输入',
               'waiting_game':'等待游戏前台','error':'输入记录故障'}.get(status,status)
        errors=state.get('errors',[])
        received=state.get('input_received',{})
        filtered=state.get('input_filtered',{})
        keyboard=max(0,received.get('key',0)-filtered.get('key',0))
        mouse=sum(max(0,received.get(k,0)-filtered.get(k,0)) for k in ('button','motion','wheel'))
        text=f'{title} · 键盘 {keyboard} · 鼠标 {mouse} · 缺失 {state.get("lost",0)} 条'
        if state.get('privilege'): text+=' · '+state['privilege']
        if errors: text+=' · '+errors[-1]
        if state.get('error'): text+=' · '+state['error'].splitlines()[-1][:180]
        if self.home_page.input_status.text()!=text:self.home_page.input_status.setText(text)
        self.home_page.input_status.setToolTip(state.get('path','')+
            f'\n文件记录 {state.get("count",0)} 条（含元数据）\n原始报告计数：{state.get("raw_received",{})}'
            f'\n管理员权限：{state.get("administrator",False)}\n采集健康状态：{state.get("capture_health",{})}')
        self.home_page.input_service_btn.setText('停止记录输入' if self.input_controller.running else '开始记录输入')
        visual_status=self.vision_controller.state['status']
        if self.home_page.vision_status.text()!=visual_status:self.home_page.vision_status.setText(visual_status)

    def _show_input_settings(self):
        from endfield_pcap.gui.independent.input_settings import InputSettingsDialog
        dialog=InputSettingsDialog(self.app_config.input_settings,self)
        if dialog.exec():
            self.app_config.input_settings=dialog.value()
            save_app_config(self.app_config,self.config_path)

    def _show_vision_settings(self):
        from endfield_pcap.gui.independent.vision_settings import VisionSettingsDialog
        self._vision_preview_active=True
        self._set_analysis_requirements(self._independent_subscriptions)
        dialog=VisionSettingsDialog(self.vision_controller,self.app_config.vision_settings,self)
        if dialog.exec():
            self.app_config.vision_settings=dialog.value()
            self.vision_controller.configure(self.app_config.vision_settings)
            save_app_config(self.app_config,self.config_path)
        self._vision_preview_active=False
        self._set_analysis_requirements(self._independent_subscriptions)

    def _stop_independent_services(self):
        self.input_controller.stop(wait=True)
        self.vision_controller.stop()
