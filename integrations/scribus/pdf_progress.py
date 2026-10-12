"""Independent cancellation UI while Scribus runs its synchronous PDF exporter."""
import json
from pathlib import Path
import time

from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QApplication,QDialog,QLabel,QProgressBar,QPushButton,QVBoxLayout


class PdfProgress(QDialog):
    def __init__(self,request):
        super().__init__()
        self.request=request
        self.started=time.monotonic()
        self.setWindowTitle('AI書き出し：PDF作成')
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,True)
        layout=QVBoxLayout(self)
        self.label=QLabel('ScribusでPDFを作成しています。中止は現在のPDF作成が終わった時点で反映します。',wordWrap=True)
        layout.addWidget(self.label)
        progress=QProgressBar();progress.setRange(0,0);layout.addWidget(progress)
        self.button=QPushButton('中止を要求');self.button.clicked.connect(lambda:self.cancel(False));layout.addWidget(self.button)
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(100)

    def cancel(self,timed_out=False):
        path=Path(self.request['cancel'])
        if not path.exists():path.write_text('timeout' if timed_out else 'cancel',encoding='utf-8')
        self.button.setEnabled(False)
        self.label.setText('制限時間を超えました。PDF作成の終了を待って中止します。' if timed_out else '中止を受け付けました。PDF作成の終了を待っています。')

    def reject(self):
        self.cancel(False)

    def poll(self):
        if Path(self.request['done']).exists():self.accept();return
        timeout=float(self.request.get('timeout_minutes',0))*60
        if timeout and time.monotonic()-self.started>=timeout:self.cancel(True)


def run(request_path):
    request=json.loads(Path(request_path).read_text(encoding='utf-8'))
    app=QApplication.instance() or QApplication(['pdf2ai-pdf-progress'])
    dialog=PdfProgress(request);dialog.show();app.processEvents()
    Path(request['ready']).touch()
    return dialog.exec()
