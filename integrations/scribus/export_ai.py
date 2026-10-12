# -*- coding: utf-8 -*-
"""Scribusで開いている文書をIllustrator CC2020形式のAIに直接書き出します。

Scribusの「スクリプト → スクリプトを実行」でこのファイルを選択します。
文字はパス化し、特色・レイヤーを含む一時PDFを既存の変換エンジンへ渡します。
複数ページは1つのAIまたはページ別のAIを選択でき、未対応機能は標準で自動画像化します。
Scribus内のPythonには追加パッケージを入れず、外部Pythonの仮想環境を使用します。
"""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from pdf2ai.i18n import tr, set_language, get_language, normalize_language, translator, use_language
from functools import wraps
RASTER_DPI = 300
STRICT = False


def scribus_language(scribus):
    """Use Scribus's UI preference, independent of the system locale."""
    try:
        return normalize_language(scribus.getGuiLanguage())
    except (AttributeError,RuntimeError):
        return 'en'


def request_language(function):
    @wraps(function)
    def wrapped(request,*args,**kwargs):
        with use_language(request.get('language',get_language())):
            return function(request,*args,**kwargs)
    return wrapped


def parse_pages(value, count, current):
    value = value.strip().lower()
    if value in ('all', '全部', '全ページ'):
        return list(range(1, count + 1))
    if value in ('current', '現在'):
        return [current]
    selected = set()
    for part in value.split(','):
        bounds = part.strip().split('-')
        if len(bounds) == 1:
            start = end = int(bounds[0])
        elif len(bounds) == 2:
            start, end = map(int, bounds)
        else:
            raise ValueError(tr('ページ番号は all / current / 1,3-5 の形式で入力してください。'))
        if not 1 <= start <= end <= count:
            raise ValueError(tr('ページ番号は1〜{}の範囲で入力してください。').format(count))
        selected.update(range(start, end + 1))
    if not selected:
        raise ValueError(tr('対象ページを指定してください。'))
    return sorted(selected)


def output_paths(base, pages, output_mode='separate'):
    if output_mode not in ('combined', 'separate'):
        raise ValueError(tr('書き出し方法は combined / separate のいずれかを指定してください。'))
    base = Path(base)
    if not base.suffix:
        base = base.with_suffix('.ai')
    if base.suffix.lower() != '.ai':
        raise ValueError(tr('出力ファイルの拡張子は .ai にしてください。'))
    if not base.parent.is_dir():
        raise ValueError(tr('出力先フォルダーが存在しません。'))
    outputs = [base] if len(pages) == 1 or output_mode == 'combined' else [base.with_name('{}_{:03d}.ai'.format(base.stem, p)) for p in pages]
    return outputs, base.with_suffix('.report.json')


def child_environment():
    environment = os.environ.copy()
    # The embedded Python environment must not override the external interpreter.
    for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        environment.pop(key, None)
    environment['PYTHONIOENCODING'] = 'utf-8'
    return environment


def run_child(command, timeout=None):
    options = {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE,
               'encoding': 'utf-8', 'errors': 'replace', 'env': child_environment(), 'timeout': timeout}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(command, **options)


def find_python():
    configured = os.environ.get('PDF2AI_PYTHON')
    if configured:
        candidates = [configured]
    else:
        candidates = [str(ROOT / '.venv' / 'Scripts' / 'python.exe'),
                      str(ROOT / '.venv' / 'bin' / 'python')]
        candidates += [shutil.which(name) for name in ('python3', 'python')]
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            result = run_child([candidate, str(Path(__file__).resolve()), '--check'], timeout=30)
            if result.returncode == 0:
                return candidate
        except (OSError, subprocess.TimeoutExpired):
            pass
    raise RuntimeError(tr('変換用Pythonまたは設定画面のパッケージを見つけられません。READMEの手順でプロジェクト内に.venvを作成し、pip install ".[scribus]"を実行してください。別の環境を使う場合はPDF2AI_PYTHONにPython実行ファイルのパスを設定してください。'))


def default_output(document):
    path = Path(document).expanduser() if document else Path('document.sla')
    if path.name.lower().endswith('.sla.gz'):
        path = path.with_suffix('')
    directory = path.absolute().parent
    if not directory.is_dir():
        directory = Path.cwd()
    return directory / path.with_suffix('.ai').name


def build_export_dialog(document, count, current, language=None):
    ui_language = normalize_language(language) if language is not None else get_language()
    tr = translator(ui_language)
    # Run Qt in the external Python process, independently of Scribus's Qt.
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                  QLineEdit, QCheckBox, QComboBox, QPushButton,
                                  QDialogButtonBox, QFileDialog, QMessageBox, QSpinBox)
    dialog = QDialog()
    dialog.setWindowTitle(tr('AI書き出し'))
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dialog.setMinimumWidth(540)
    dialog.export_options = None
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(tr('対象ページ：all（全ページ） / current（現在） / 例：1,3-5')))
    pages = QLineEdit('all')
    pages.setObjectName('pages')
    layout.addWidget(pages)
    layout.addWidget(QLabel(tr('書き出し方法')))
    output_mode = QComboBox()
    output_mode.setObjectName('output_mode')
    output_mode.addItem(tr('ページ別のAIファイル'), 'separate')
    output_mode.addItem(tr('対象ページを1つのAIファイルにまとめる'), 'combined')
    layout.addWidget(output_mode)
    layout.addWidget(QLabel(tr('保存先')))
    row = QHBoxLayout()
    destination = QLineEdit(str(default_output(document)))
    destination.setObjectName('output')
    row.addWidget(destination)
    browse = QPushButton(tr('参照…'))
    row.addWidget(browse)
    layout.addLayout(row)
    report = QCheckBox(tr('JSONログを出力する'))
    report.setObjectName('write_report')
    report.setChecked(False)
    layout.addWidget(report)
    strict = QCheckBox(tr('未対応機能があれば画像化せずエラーにする'))
    strict.setObjectName('strict')
    strict.setChecked(STRICT)
    layout.addWidget(strict)
    layout.addWidget(QLabel(tr('画像化する場合の解像度（dpi）')))
    dpi = QSpinBox()
    dpi.setObjectName('raster_dpi')
    dpi.setRange(72, 1200)
    dpi.setValue(int(RASTER_DPI))
    layout.addWidget(dpi)
    layout.addWidget(QLabel(tr('検査・変換の制限時間（各処理／分。0は制限なし）')))
    timeout = QSpinBox()
    timeout.setObjectName('timeout_minutes')
    timeout.setRange(0,1440)
    layout.addWidget(timeout)
    bleeds = QCheckBox(tr('文書の裁ち落としを含める'))
    bleeds.setObjectName('bleeds')
    layout.addWidget(bleeds)
    marks = QCheckBox(tr('トンボを付ける'))
    marks.setObjectName('crop_marks')
    layout.addWidget(marks)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('書き出し'))
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('キャンセル'))
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('キャンセル'))
    layout.addWidget(buttons)

    def choose_file():
        chosen, _ = QFileDialog.getSaveFileName(dialog, tr('AI書き出し：保存先'), destination.text(), 'Illustrator (*.ai)',
                                              options=QFileDialog.Option.DontConfirmOverwrite | QFileDialog.Option.DontUseNativeDialog)
        if chosen:
            destination.setText(chosen)

    def accept():
        try:
            with use_language(ui_language):
                selected = parse_pages(pages.text(), count, current)
                chosen = destination.text().strip()
                if not chosen:
                    raise ValueError(tr('保存先を指定してください。'))
                output_paths(chosen, selected, output_mode.currentData())
        except ValueError as error:
            QMessageBox.warning(dialog, tr('AI書き出し'), str(error))
            return
        dialog.export_options = {'pages': selected, 'output': chosen, 'write_report': report.isChecked(),
                                 'output_mode': output_mode.currentData(), 'strict': strict.isChecked(),
                                 'dpi': dpi.value(), 'bleeds': bleeds.isChecked(), 'crop_marks': marks.isChecked(),
                                 'timeout_minutes': timeout.value(),
                                 'language':ui_language}
        dialog.accept()

    browse.clicked.connect(choose_file)
    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    return dialog


def export_dialog(document, count, current, language=None):
    from PySide6.QtWidgets import QApplication, QDialog
    app = QApplication.instance() or QApplication(['pdf2ai-scribus'])
    from qt_language import configure_qt_language
    configure_qt_language(app,language if language is not None else get_language())
    dialog = build_export_dialog(document, count, current, language)
    return dialog.export_options if dialog.exec() == QDialog.DialogCode.Accepted else None


def export_pdf(scribus, path, pages, options=None):
    pdf = scribus.PDFfile()
    settings = {'file': str(path), 'pages': pages, 'version': 15, 'useLayers': True,
                'fontEmbedding': 1, 'usespot': True, 'outdst': 1, 'profiles': False,
                'profilei': False, 'noembicc': True, 'encrypt': False, 'domulti': False,
                'compress': True, 'compressmtd': 2, 'quality': 0, 'resolution': 300,
                'downsample': 0, 'embedPDF': True, 'isGrayscale': False,
                'mirrorH': False, 'mirrorV': False, 'presentation': False, 'doClip': False,
                'cropMarks': False, 'bleedMarks': False, 'registrationMarks': False,
                'colorMarks': False, 'docInfoMarks': False,
                'useDocBleeds': False, 'bleedt': 0, 'bleedb': 0, 'bleedl': 0, 'bleedr': 0}
    options = options or {}
    settings['useDocBleeds'] = bool(options.get('bleeds', False))
    settings['cropMarks'] = bool(options.get('crop_marks', False))
    for name, value in settings.items():
        setattr(pdf, name, value)
    pdf.save()
    if not Path(path).is_file() or not Path(path).stat().st_size:
        raise RuntimeError(tr('ScribusのPDF書き出しが完了しませんでした。'))


def export_pdf_monitored(scribus,path,pages,options,python):
    """Accept cancellation during synchronous save; stop before any AI conversion."""
    import time
    directory=Path(path).parent
    control={name:str(directory/('pdf-progress-'+name)) for name in ('ready','cancel','done')}
    control['timeout_minutes']=options.get('timeout_minutes',0)
    control['language']=options.get('language',get_language())
    request=directory/'pdf-progress.json'
    request.write_text(json.dumps(control),encoding='utf-8')
    launch={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    process=subprocess.Popen([python,str(Path(__file__).resolve()),'--pdf-progress',str(request)],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=child_environment(),**launch)
    started=time.monotonic()
    status=None
    try:
        while not Path(control['ready']).exists():
            if process.poll() is not None or time.monotonic()-started>15:
                raise RuntimeError(tr('PDF作成の進捗画面を開始できませんでした。'))
            time.sleep(.02)
        if not Path(control['cancel']).exists():export_pdf(scribus,path,pages,options)
        if process.poll() is not None:
            raise RuntimeError(tr('PDF作成の進捗画面が終了しました。AI変換は開始していません。'))
        timeout=float(control['timeout_minutes'])*60
        timed_out=bool(timeout and time.monotonic()-started>=timeout)
        cancel=Path(control['cancel'])
        if cancel.exists():timed_out=timed_out or cancel.read_text(encoding='utf-8')=='timeout'
        status={'cancelled':cancel.exists() or timed_out,'timed_out':timed_out}
    finally:
        Path(control['done']).touch()
        try:process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill();process.communicate()
        # Include a click received between PDF completion and closing the UI.
        cancel=Path(control['cancel'])
        if status is not None and cancel.exists():
            status.update(cancelled=True,timed_out=status['timed_out'] or cancel.read_text(encoding='utf-8')=='timeout')
    return status


def prepare_request(request):
    sys.path.insert(0, str(ROOT / 'src'))
    import pikepdf
    source = Path(request['pdf'])
    pages = request['pages']
    if not pages or any(type(p) is not int or p < 1 for p in pages) or len(set(pages)) != len(pages):
        raise ValueError('Invalid page selection')
    dpi = float(request.get('dpi', RASTER_DPI))
    if not math.isfinite(dpi) or not 72 <= dpi <= 1200:
        raise ValueError('Raster DPI must be between 72 and 1200')
    output_mode = request.get('output_mode', 'separate')
    outputs, report_path = output_paths(request['output'], pages, output_mode)
    destinations = outputs + ([report_path] if request.get('write_report', False) else [])
    if any(path.is_dir() for path in destinations):
        raise ValueError(tr('出力先がファイルではなくフォルダーです。保存先を変更してください。'))
    if not request.get('overwrite', False):
        existing = [path for path in destinations if os.path.lexists(path)]
        if existing:
            raise FileExistsError(tr('出力が既に存在します: ') + ', '.join(path.name for path in existing))
    from pdf2ai.path_conflicts import paths_conflict
    if any(paths_conflict(source, path) for path in destinations):
        raise ValueError('Input/output path conflict')
    with pikepdf.open(source) as pdf:
        if pdf.is_encrypted:raise ValueError('Encrypted PDFs are unsupported')
        if len(pdf.pages) != len(pages):
            raise ValueError(tr('ScribusのPDFページ数が対象ページ数と一致しません。'))
    return source,pages,dpi,output_mode,outputs,report_path


@request_language
def inspect_export(request, emit=lambda event: None):
    source,pages,dpi,mode,outputs,report_path = prepare_request(request)
    from pdf2ai.preflight import inspect_document, inspect_combination
    results = []
    if mode == 'combined':
        results = inspect_combination(source, list(range(1,len(pages)+1)), dpi,
            page_labels=pages, raster_fallback=not request.get('strict',STRICT),
            progress=lambda page,done,total: emit({'phase':'inspect','current':done,'total':total,'page':page}))
    else:
        emit({'phase':'inspect','current':0,'total':len(pages)})
        results = inspect_document(source,raster_dpi=dpi,
            progress=lambda number,done,total: emit({'phase':'inspect','current':done,'total':total,'page':pages[number-1]}))
        for item,page in zip(results,pages):item['page'] = page
    emit({'phase':'inspect','current':len(pages),'total':len(pages)})
    return {'inspection_only':True,'results':results,'language':get_language(),
            'strict':bool(request.get('strict',STRICT)),
            'can_export':not any(r.get('combined_blocker') for r in results) and
                (not request.get('strict',STRICT) or all(r['native_supported'] for r in results)),
            'combined_constraints_checked':mode == 'combined'}


def wait_for_publication(request, emit, total):
    import time
    permit = request.get('commit_permission')
    if permit:
        emit({'phase':'ready_to_publish','current':total,'total':total})
        deadline = time.monotonic()+60
        while not Path(permit).exists():
            if time.monotonic()>deadline:raise RuntimeError(tr('出力公開の確認を受け取れませんでした。AIは公開していません。'))
            time.sleep(.02)
    else:emit({'phase':'publish','current':total,'total':total})


@request_language
def convert_export(request, emit=lambda event: None):
    source,pages,dpi,mode,outputs,report_path = prepare_request(request)
    from pdf2ai.native import convert
    from pdf2ai.batch_publish import publish_batch
    results = []
    summary = {'document':request.get('document','Scribus document'),
               'output_mode':mode,'results':results,'committed':False,'language':get_language()}
    with tempfile.TemporaryDirectory(prefix='.pdf2ai-batch-',dir=request.get('work_dir',outputs[0].parent)) as directory:
        staging = Path(directory)
        staged = [staging/p.name for p in outputs]
        if mode == 'combined':
            from pdf2ai.multiboard import convert_document
            emit({'phase':'convert','current':0,'total':len(pages)})
            try:
                # Only this single staged AI is created; no final output is visible.
                results.extend(convert_document(source,staged[0],page_labels=pages,
                    raster_fallback=not request.get('strict',STRICT),raster_dpi=dpi,
                    progress=lambda page,done,total: emit({'phase':'convert','current':done,'total':total,'page':page})))
            except Exception as error:
                results.extend({'page':p,'output':outputs[0].name,'error':str(error)} for p in pages)
        else:
            for index,(page,output) in enumerate(zip(pages,staged),1):
                emit({'phase':'convert','current':index-1,'total':len(pages),'page':page})
                try:
                    result = convert(source,output,page_number=index,
                        raster_fallback=not request.get('strict',STRICT),raster_dpi=dpi)
                    result['page'] = page
                except Exception as error:
                    result = {'page':page,'output':output.name,'error':str(error)}
                results.append(result)
                emit({'phase':'convert','current':index,'total':len(pages),'page':page})
        for result in results:
            result['input'] = request.get('document','Scribus document')
            result['output'] = outputs[0].name if mode=='combined' else outputs[pages.index(result['page'])].name
            result['published'] = False
        success = all('error' not in r for r in results)
        files = list(zip(staged,outputs)) if success else []
        if success:
            summary['committed'] = True
            for result in results:result['published'] = True
        if request.get('write_report',False):
            staged_report = staging/report_path.name
            staged_report.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            files.append((staged_report,report_path))
        if files:
            wait_for_publication(request,emit,len(pages))
            try:publish_batch(files,overwrite=bool(request.get('overwrite',False)))
            except Exception:
                summary['committed'] = False
                for result in results:result['published'] = False
                raise
    return summary


def scribus_main(scribus):
    with use_language(scribus_language(scribus)):
        return _scribus_main(scribus)


def _scribus_main(scribus):
    if not scribus.haveDoc():
        scribus.messageBox(tr('AI書き出し'), tr('書き出す文書を開いてください。'), scribus.ICON_WARNING)
        return
    python = find_python()
    document_name = scribus.getDocName() or ''
    document = Path(document_name or 'document.sla')
    selection = run_child([python, str(Path(__file__).resolve()), '--dialog', '--document', document_name,
                           '--count', str(scribus.pageCount()), '--current', str(scribus.currentPage()),
                           '--language',get_language()])
    if selection.returncode != 0:
        raise RuntimeError((selection.stderr or tr('設定画面を開始できませんでした。')).strip()[-2000:])
    options = json.loads(selection.stdout)
    if options is None:
        return
    pages, chosen = options['pages'], options['output']
    write_report = options['write_report']
    output_mode = options.get('output_mode', 'separate')
    outputs, report_path = output_paths(chosen, pages, output_mode)
    existing = [p for p in outputs + ([report_path] if write_report else []) if p.exists()]
    overwrite = False
    if existing:
        answer = scribus.messageBox(tr('AI書き出し：上書き'), tr('{}件の既存ファイルを上書きしますか？\n{}').format(len(existing), '\n'.join(p.name for p in existing[:8])),
                                    scribus.ICON_WARNING, scribus.BUTTON_NO | scribus.BUTTON_DEFAULT, scribus.BUTTON_YES)
        if answer != scribus.BUTTON_YES:
            return
        overwrite = True
    scribus.statusMessage(tr('AI書き出し：PDFを作成しています…'))
    scribus.progressReset()
    scribus.progressTotal(2)
    try:
        with tempfile.TemporaryDirectory(prefix='.pdf2ai-scribus-', dir=outputs[0].parent) as directory:
            directory = Path(directory)
            pdf = directory / 'document.pdf'
            pdf_status=export_pdf_monitored(scribus,pdf,pages,options,python)
            if pdf_status['cancelled']:
                scribus.messageBox(tr('AI書き出し'),tr('PDF作成が制限時間を超えたため中止しました。AIは保存していません。') if pdf_status['timed_out'] else tr('PDF作成後に中止しました。AIは保存していません。'),scribus.ICON_INFORMATION)
                return
            request = {'pdf': str(pdf), 'pages': pages, 'output': str(Path(chosen)),
                       'overwrite': overwrite, 'strict': options.get('strict', STRICT),
                       'dpi': options.get('dpi', RASTER_DPI), 'document': document.name,
                       'write_report': write_report, 'output_mode': output_mode,
                       'timeout_minutes':options.get('timeout_minutes',0),'language':get_language()}
            request_path = directory / 'request.json'
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
            scribus.progressSet(1)
            scribus.statusMessage(tr('AI書き出し：{}ページを変換しています…').format(len(pages)))
            result = run_child([python, str(Path(__file__).resolve()), '--export-session', str(request_path)])
            if result.returncode not in (0, 1):
                raise RuntimeError((result.stderr or result.stdout or tr('変換処理を開始できませんでした。')).strip()[-2000:])
            summary = json.loads(result.stdout)
        if summary.get('cancelled'):
            scribus.messageBox(tr('AI書き出し'),tr('制限時間を超えたため停止しました。AIは公開していません。') if summary.get('timed_out') else tr('書き出しをキャンセルしました。AIは公開していません。'),scribus.ICON_INFORMATION)
            return
        if summary.get('error'):raise RuntimeError(summary['error'])
        errors = [r for r in summary['results'] if 'error' in r]
        rasterized = [r for r in summary['results'] if r.get('rasterized')]
        saved = len(pages) if summary.get('committed') else 0
        lines = [tr('保存：{} / 保存済み{}ページ').format(outputs[0].parent,saved)]
        if not summary.get('committed'):lines.append(tr('一部の変換に失敗したため、AIは一式を公開していません。既存AIを保持します。'))
        lines.append(tr('書き出し方法：') + (tr('1つのAIファイル（{v0}）',v0=outputs[0].name) if output_mode == 'combined' else tr('ページ別のAIファイル')))
        if write_report:
            lines.append(tr('レポート：') + report_path.name)
        if rasterized:
            lines += [tr('画像化したページ：') + ', '.join(str(r['page']) for r in rasterized),
                      tr('画像化したページは文字・パス・特色・レイヤーを個別に再編集できません。')]
            lines += [tr('ページ{}：{}').format(r['page'], r['fallback_reason']) for r in rasterized[:5]]
        lines += [tr('ページ{}：{}').format(r['page'], r['error']) for r in errors[:5]]
        scribus.progressSet(2)
        scribus.messageBox(tr('AI書き出し'), '\n'.join(lines), scribus.ICON_WARNING if errors or rasterized else scribus.ICON_INFORMATION)
    finally:
        scribus.progressReset()
        scribus.statusMessage('')


def main():
    if any(flag in sys.argv for flag in ('--check', '--worker', '--dialog','--inspect','--export-session','--pdf-progress')):
        parser = argparse.ArgumentParser()
        parser.add_argument('--check', action='store_true')
        parser.add_argument('--worker', type=Path)
        parser.add_argument('--inspect',type=Path)
        parser.add_argument('--export-session',type=Path)
        parser.add_argument('--pdf-progress',type=Path)
        parser.add_argument('--events',action='store_true')
        parser.add_argument('--dialog', action='store_true')
        parser.add_argument('--document', default='')
        parser.add_argument('--count', type=int)
        parser.add_argument('--current', type=int)
        parser.add_argument('--language',choices=('en','ja'),default='en')
        args = parser.parse_args()
        set_language(args.language)
        try:
            sys.path.insert(0, str(ROOT / 'src'))
            from pdf2ai.native import convert
            if args.check:
                from PySide6 import QtWidgets
                print('pdf2ai ready')
                return 0
            if args.pdf_progress:
                from pdf_progress import run
                run(args.pdf_progress)
                return 0
            if args.dialog:
                print(json.dumps(export_dialog(args.document, args.count, args.current, args.language), ensure_ascii=False))
                return 0
            if args.export_session:
                from progress_dialog import run_export_session
                summary = run_export_session(args.export_session,Path(__file__).resolve())
            else:
                emit = (lambda event: print(json.dumps(event,ensure_ascii=False),flush=True)) if args.events else (lambda event: None)
                config = args.inspect or args.worker
                request = json.loads(config.read_text(encoding='utf-8'))
                summary = inspect_export(request,emit) if args.inspect else convert_export(request,emit)
            print(json.dumps({'kind':'result','summary':summary} if args.events else summary, ensure_ascii=False),flush=True)
            if summary.get('error'):return 1
            return int(any('error' in r for r in summary['results']))
        except Exception as error:
            print(str(error), file=sys.stderr)
            return 2
    try:
        import scribus
    except ImportError:
        set_language('en')
        print(tr('このスクリプトはScribusの「スクリプトを実行」から起動してください。'), file=sys.stderr)
        return 2
    with use_language(scribus_language(scribus)):
        try:
            scribus_main(scribus)
        except Exception as error:
            scribus.messageBox(tr('AI書き出し：エラー'), str(error), scribus.ICON_CRITICAL)
            return 1
    return 0


if __name__ == '__main__':
    # Scribus shares its interpreter with the host; never call sys.exit there.
    result = main()
    if any(flag in sys.argv for flag in ('--worker', '--check', '--dialog','--inspect','--export-session')):
        raise SystemExit(result)
