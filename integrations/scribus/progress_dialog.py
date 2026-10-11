"""Responsive progress and preflight dialogs exclusively for Scribus export."""
import json
import codecs
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QProcess, QTimer, Qt, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QProgressBar,
                              QPushButton, QPlainTextEdit, QDialogButtonBox)


def build_preflight_dialog(summary):
    dialog = QDialog()
    dialog.setWindowTitle('AI書き出し：書き出し前チェック')
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,True)
    dialog.setMinimumSize(600,400)
    layout = QVBoxLayout(dialog)
    unsupported = [r for r in summary['results'] if not r['native_supported']]
    layout.addWidget(QLabel(f"対象 {len(summary['results'])}ページ／画像化が必要 {len(unsupported)}ページ"))
    if unsupported:
        layout.addWidget(QLabel('画像化したページでは文字・パス・特色・レイヤーの個別編集が失われます。',wordWrap=True))
    details = QPlainTextEdit()
    details.setObjectName('preflight_details')
    details.setReadOnly(True)
    lines = []
    for item in summary['results']:
        lines.append(f"ページ{item['page']}："+('ベクター変換可能' if item['native_supported'] else '画像化が必要：'+item['first_blocker']))
        lines.extend('  '+warning for warning in item.get('warnings',[]))
    lines.append('各ページの最初の未対応理由を表示します。結合の配置・色空間制約は変換時に検査します。')
    details.setPlainText('\n'.join(lines))
    layout.addWidget(details)
    if not summary['can_export']:
        layout.addWidget(QLabel('画像化禁止が有効のため書き出せません。設定を変更して再実行してください。',wordWrap=True))
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText('書き出し')
    buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(summary['can_export'])
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('キャンセル')
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return dialog


class ExportSession(QDialog):
    phase_event = Signal(object)

    def __init__(self,request_path,worker_script,approve=None):
        super().__init__()
        self.request_path = Path(request_path)
        self.request = json.loads(self.request_path.read_text(encoding='utf-8'))
        self.approve = approve
        self.worker_script = str(worker_script)
        self.summary = None
        self.pending = None
        self.buffer = ''
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.mode = None
        self.cancelled = self.timed_out = self.publishing = False
        self.permission = self.request_path.parent/'commit.permission'
        self.permission.unlink(missing_ok=True)
        self.request['commit_permission'] = str(self.permission)
        self.request['work_dir'] = str(self.request_path.parent)
        self.request_path.write_text(json.dumps(self.request,ensure_ascii=False),encoding='utf-8')
        minutes = self.request.get('timeout_minutes',0)
        if type(minutes) is not int or not 0<=minutes<=1440:raise ValueError('Invalid timeout')
        self.limit = minutes*60
        self.setWindowTitle('Scribus：AI書き出し')
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,True)
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        self.label = QLabel('書き出し前チェックを開始します。')
        self.label.setObjectName('export_status')
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.progress = QProgressBar()
        self.progress.setRange(0,len(self.request['pages']))
        layout.addWidget(self.progress)
        self.cancel_button = QPushButton('キャンセル')
        self.cancel_button.clicked.connect(self.cancel)
        layout.addWidget(self.cancel_button)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.receive)
        self.process.finished.connect(self.worker_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.check_timeout)

    def start(self,mode='inspect'):
        if self.cancelled:return
        self.mode = mode
        self.pending = None
        self.buffer = ''
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.progress.setValue(0)
        self.started = time.monotonic()
        self.timer.start()
        self.process.start(sys.executable,[self.worker_script,'--'+mode,str(self.request_path),'--events'])

    def receive(self):
        self.buffer += self.decoder.decode(bytes(self.process.readAllStandardOutput()))
        while '\n' in self.buffer:
            line,self.buffer = self.buffer.split('\n',1)
            if not line.strip():continue
            event = json.loads(line)
            if event.get('kind')=='result':
                self.pending = event['summary']
                continue
            self.phase_event.emit(event)
            if self.cancelled:continue
            phase = event['phase']
            self.progress.setValue(event.get('current',0))
            if phase=='inspect':
                self.label.setText(f"書き出し前チェック：{event['current']}/{event['total']}ページ")
            elif phase=='convert':
                self.label.setText(f"変換中：{event['current']}/{event['total']}ページ（出力AIはまだ保存していません）")
            elif phase=='ready_to_publish':
                self.publishing = True
                self.cancel_button.setEnabled(False)
                self.timer.stop()
                self.label.setText('出力ファイルを保存しています。保存・復元の完了を待っています。')
                try:
                    temporary = self.permission.with_suffix('.ready')
                    temporary.write_bytes(b'commit')
                    os.replace(temporary,self.permission)
                except OSError:
                    self.publishing = False
                    self.process.kill()

    def check_timeout(self):
        if self.limit and time.monotonic()-self.started>=self.limit:
            self.timed_out = True
            self.cancel()

    def cancel(self):
        if self.publishing:return
        self.cancelled = True
        self.timer.stop()
        self.cancel_button.setEnabled(False)
        self.label.setText('変換を停止しています。AIは公開しません。')
        if self.process.state()!=QProcess.ProcessState.NotRunning:self.process.kill()
        else:self.worker_finished(-1,QProcess.ExitStatus.CrashExit)

    def reject(self):
        self.cancel()

    def process_error(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            self.worker_finished(-1,QProcess.ExitStatus.CrashExit)

    def worker_finished(self,code,status):
        self.timer.stop()
        self.receive()
        if self.cancelled:
            self.summary = {'committed':False,'cancelled':True,'timed_out':self.timed_out,'results':[]}
        elif code not in (0,1) or self.pending is None:
            message = bytes(self.process.readAllStandardError()).decode('utf-8',errors='replace').strip()
            self.summary = {'committed':False,'error':message or self.process.errorString(),'results':[]}
        elif self.mode=='inspect':
            summary = self.pending
            needs_confirmation = not summary['can_export'] or any(
                not item['native_supported'] or item.get('warnings') for item in summary['results'])
            allowed = True
            if needs_confirmation:
                allowed = self.approve(summary) if self.approve is not None else build_preflight_dialog(summary).exec()==QDialog.DialogCode.Accepted
            if allowed and summary['can_export']:
                self.label.setText('変換を開始します。')
                self.start('worker')
                return
            self.summary = {'committed':False,'cancelled':True,'preflight_rejected':True,'results':[],'inspection':summary}
        else:self.summary = self.pending
        self.accept()


def run_export_session(request_path,worker_script):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(['pdf2ai-scribus-export'])
    session = ExportSession(request_path,worker_script)
    QTimer.singleShot(0,session.start)
    session.exec()
    return session.summary
