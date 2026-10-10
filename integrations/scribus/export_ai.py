# -*- coding: utf-8 -*-
"""Scribusで開いている文書をIllustrator CC2020形式のAIに直接書き出します。

Scribusの「スクリプト → スクリプトを実行」でこのファイルを選択します。
文字はパス化し、特色・レイヤーを含む一時PDFを既存の変換エンジンへ渡します。
複数ページはページごとのAIになり、未対応機能は標準で自動画像化します。
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
RASTER_DPI = 300
STRICT = False


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
            raise ValueError('ページ番号は all / current / 1,3-5 の形式で入力してください。')
        if not 1 <= start <= end <= count:
            raise ValueError('ページ番号は1〜{}の範囲で入力してください。'.format(count))
        selected.update(range(start, end + 1))
    if not selected:
        raise ValueError('対象ページを指定してください。')
    return sorted(selected)


def output_paths(base, pages):
    base = Path(base)
    if not base.suffix:
        base = base.with_suffix('.ai')
    if base.suffix.lower() != '.ai':
        raise ValueError('出力ファイルの拡張子は .ai にしてください。')
    if not base.parent.is_dir():
        raise ValueError('出力先フォルダーが存在しません。')
    outputs = [base] if len(pages) == 1 else [base.with_name('{}_{:03d}.ai'.format(base.stem, p)) for p in pages]
    return outputs, base.with_suffix('.report.json')


def child_environment():
    environment = os.environ.copy()
    # The embedded Python environment must not override the external interpreter.
    for key in ('PYTHONHOME', 'PYTHONPATH'):
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
    raise RuntimeError('変換用Pythonを見つけられません。READMEの手順でプロジェクト内に.venvを作成し、pip install .を実行してください。別の環境を使う場合はPDF2AI_PYTHONにPython実行ファイルのパスを設定してください。')


def export_pdf(scribus, path, pages):
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
    for name, value in settings.items():
        setattr(pdf, name, value)
    pdf.save()
    if not Path(path).is_file() or not Path(path).stat().st_size:
        raise RuntimeError('ScribusのPDF書き出しが完了しませんでした。')


def convert_export(request):
    sys.path.insert(0, str(ROOT / 'src'))
    import pikepdf
    from pdf2ai.native import convert
    source = Path(request['pdf'])
    pages = request['pages']
    if not pages or any(type(p) is not int or p < 1 for p in pages) or len(set(pages)) != len(pages):
        raise ValueError('Invalid page selection')
    dpi = float(request.get('dpi', RASTER_DPI))
    if not math.isfinite(dpi) or not 72 <= dpi <= 1200:
        raise ValueError('Raster DPI must be between 72 and 1200')
    outputs, report_path = output_paths(request['output'], pages)
    overwrite = bool(request.get('overwrite', False))
    if not overwrite:
        existing = [path for path in outputs + [report_path] if path.exists()]
        if existing:
            raise FileExistsError('出力が既に存在します: ' + ', '.join(path.name for path in existing))
    if source.resolve() in {p.resolve() for p in outputs + [report_path]}:
        raise ValueError('Input/output path conflict')
    with pikepdf.open(source) as pdf:
        if len(pdf.pages) != len(pages):
            raise ValueError('ScribusのPDFページ数が対象ページ数と一致しません。')
    results = []
    for index, (page, output) in enumerate(zip(pages, outputs), 1):
        try:
            report = convert(source, output, page_number=index, overwrite=overwrite,
                             raster_fallback=not request.get('strict', STRICT), raster_dpi=dpi)
            report['input'] = request.get('document', 'Scribus document')
            report['page'] = page
            report['output'] = output.name
        except Exception as error:
            report = {'page': page, 'output': output.name, 'error': str(error)}
        results.append(report)
    summary = {'document': request.get('document', 'Scribus document'), 'results': results}
    # Publish the report without truncating a previous file on failure/races.
    descriptor, temporary = tempfile.mkstemp(prefix='.pdf2ai-report-', dir=report_path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        if overwrite:
            os.replace(temporary, report_path)
        else:
            os.link(temporary, report_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return summary


def scribus_main(scribus):
    if not scribus.haveDoc():
        scribus.messageBox('AI書き出し', '書き出す文書を開いてください。', scribus.ICON_WARNING)
        return
    value = scribus.valueDialog('AI書き出し：対象ページ', 'all：全ページ / current：現在のページ / 例：1,3-5', 'all')
    if not value:
        return
    pages = parse_pages(value, scribus.pageCount(), scribus.currentPage())
    document = Path(scribus.getDocName() or 'document.sla')
    chosen = scribus.fileDialog('AI書き出し：保存先', 'Illustrator (*.ai)', str(document.with_suffix('.ai')), False, True)
    if not chosen:
        return
    outputs, report_path = output_paths(chosen, pages)
    existing = [p for p in outputs + [report_path] if p.exists()]
    overwrite = False
    if existing:
        answer = scribus.messageBox('AI書き出し：上書き', '{}件の既存ファイルを上書きしますか？\n{}'.format(len(existing), '\n'.join(p.name for p in existing[:8])),
                                    scribus.ICON_WARNING, scribus.BUTTON_NO | scribus.BUTTON_DEFAULT, scribus.BUTTON_YES)
        if answer != scribus.BUTTON_YES:
            return
        overwrite = True
    python = find_python()
    scribus.statusMessage('AI書き出し：PDFを作成しています…')
    scribus.progressReset()
    scribus.progressTotal(2)
    try:
        with tempfile.TemporaryDirectory(prefix='.pdf2ai-scribus-', dir=outputs[0].parent) as directory:
            directory = Path(directory)
            pdf = directory / 'document.pdf'
            export_pdf(scribus, pdf, pages)
            request = {'pdf': str(pdf), 'pages': pages, 'output': str(Path(chosen)),
                       'overwrite': overwrite, 'strict': STRICT, 'dpi': RASTER_DPI, 'document': document.name}
            request_path = directory / 'request.json'
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
            scribus.progressSet(1)
            scribus.statusMessage('AI書き出し：{}ページを変換しています…'.format(len(pages)))
            result = run_child([python, str(Path(__file__).resolve()), '--worker', str(request_path)])
            if result.returncode not in (0, 1) or not report_path.is_file():
                raise RuntimeError((result.stderr or result.stdout or '変換処理を開始できませんでした。').strip()[-2000:])
            summary = json.loads(report_path.read_text(encoding='utf-8'))
        errors = [r for r in summary['results'] if 'error' in r]
        rasterized = [r for r in summary['results'] if r.get('rasterized')]
        lines = ['保存：{} / 成功{}ページ'.format(outputs[0].parent, len(pages) - len(errors)), 'レポート：' + report_path.name]
        if rasterized:
            lines += ['画像化したページ：' + ', '.join(str(r['page']) for r in rasterized),
                      '画像化したページは文字・パス・特色・レイヤーを個別に再編集できません。']
            lines += ['ページ{}：{}'.format(r['page'], r['fallback_reason']) for r in rasterized[:5]]
        lines += ['ページ{}：{}'.format(r['page'], r['error']) for r in errors[:5]]
        scribus.progressSet(2)
        scribus.messageBox('AI書き出し', '\n'.join(lines), scribus.ICON_WARNING if errors or rasterized else scribus.ICON_INFORMATION)
    finally:
        scribus.progressReset()
        scribus.statusMessage('')


def main():
    if '--check' in sys.argv or '--worker' in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument('--check', action='store_true')
        parser.add_argument('--worker', type=Path)
        args = parser.parse_args()
        try:
            sys.path.insert(0, str(ROOT / 'src'))
            from pdf2ai.native import convert
            if args.check:
                print('pdf2ai ready')
                return 0
            summary = convert_export(json.loads(args.worker.read_text(encoding='utf-8')))
            return int(any('error' in r for r in summary['results']))
        except Exception as error:
            print(str(error), file=sys.stderr)
            return 2
    try:
        import scribus
    except ImportError:
        print('このスクリプトはScribusの「スクリプトを実行」から起動してください。', file=sys.stderr)
        return 2
    try:
        scribus_main(scribus)
    except Exception as error:
        scribus.messageBox('AI書き出し：エラー', str(error), scribus.ICON_CRITICAL)
        return 1
    return 0


if __name__ == '__main__':
    # Scribus shares its interpreter with the host; never call sys.exit there.
    result = main()
    if '--worker' in sys.argv or '--check' in sys.argv:
        raise SystemExit(result)
