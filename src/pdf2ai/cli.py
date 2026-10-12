from __future__ import annotations
import argparse
from contextlib import ExitStack
import json
import os
import math
import tempfile
from pathlib import Path
import sys
import subprocess
import pikepdf
from .native import convert
from .vector import ConversionError
from .multiboard import convert_document
from .path_conflicts import duplicate_destinations, paths_conflict


def select_pages(expression, count):
    if type(count) is not int or count < 1:
        raise ConversionError('PDFに変換対象ページがありません')
    if not isinstance(expression,str) or not expression.strip():
        raise ConversionError('対象ページを指定してください（all または 1,3-5）')
    expression = expression.strip()
    if expression == 'all':
        return list(range(1, count + 1))
    result = []
    try:
        for token in expression.split(','):
            ends = [int(v.strip()) for v in token.split('-')]
            if len(ends) == 1:
                values = ends
            elif len(ends) == 2 and 1 <= ends[0] <= ends[1] <= count:
                values = range(ends[0], ends[1]+1)
            else:
                raise ValueError()
            for number in values:
                if not 1 <= number <= count or number in result:
                    raise ValueError()
                result.append(number)
    except ValueError as exc:
        raise ConversionError('ページ指定は all または 1,3-5 の形式で、重複なく指定してください') from exc
    return result


def publish_report(path, results, *, overwrite=False):
    descriptor, temporary = tempfile.mkstemp(prefix='.pdf2ai-report-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(results, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PDFのパスと特色からIllustrator 2020編集データを生成する実験的ツール")
    parser.add_argument("inputs",nargs="+",type=Path,help="入力PDF（複数指定可）")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("-o","--output",type=Path,help="出力AI（入力が1件の場合）")
    destination.add_argument("--output-dir",type=Path,help="出力先ディレクトリ")
    parser.add_argument("--page",type=int,help="複数ページPDFの対象ページ（1から）")
    parser.add_argument("--pages",help="all または 1,3-5。既定はページ別出力")
    parser.add_argument("--combine",action="store_true",help="選択ページを1つのAIにまとめる（既定は全ページ）")
    parser.add_argument('--check',action='store_true',help='AIを作らず全ページのベクター対応可否を検査')
    parser.add_argument("--outline-text",action="store_true",help="Ghostscriptで文字をアウトライン化して取り込む")
    parser.add_argument("--ghostscript",help="Ghostscript実行ファイルのパス")
    authentication = parser.add_mutually_exclusive_group()
    authentication.add_argument('--ask-password', action='store_true', help='PDFパスワードを非表示で入力')
    authentication.add_argument('--password-file', type=Path, help='PDFパスワードをUTF-8ファイルの先頭行から読む')
    parser.add_argument('--flatten-annotations', action='store_true', help='注釈・フォームの外観を通常の図形に取り込む（対話機能は失われる）')
    parser.add_argument("--strict",action="store_true",help="未対応機能を画像化せずエラーにする")
    parser.add_argument("--raster-dpi",type=float,default=300,help="自動画像化の解像度（72〜1200、既定300dpi）")
    parser.add_argument("--overwrite",action="store_true",help="既存出力を上書き")
    parser.add_argument("--report",type=Path,help="結果をJSONで保存")
    parser.add_argument('--timeout',type=float,default=0,help='各AI変換の制限秒数（0は制限なし）。超過時は一式を保存せず停止')
    args = parser.parse_args(argv)
    password = None
    if not math.isfinite(args.timeout) or args.timeout < 0:
        print('ERROR: 変換の制限時間は0以上の有限秒数で指定してください。',file=sys.stderr)
        return 1
    try:
        if args.ask_password:
            import getpass
            password = getpass.getpass('PDF password: ')
        elif args.password_file:
            with args.password_file.open(encoding='utf-8') as stream:
                password = stream.readline().rstrip('\r\n')
    except (ConversionError, OSError, UnicodeError, EOFError) as error:
        print(f'ERROR: パスワードを読み取れませんでした: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('パスワード入力を中止しました。',file=sys.stderr)
        return 130
    if args.output and len(args.inputs)!=1: parser.error("--outputは入力1件で使用してください")
    if args.page is not None and args.page<1: parser.error("--pageは1以上にしてください")
    if args.page is not None and (args.pages is not None or args.combine): parser.error('--pageと--pages/--combineは併用できません')
    if args.check:
        if args.output or args.output_dir or args.outline_text:
            parser.error('--checkは出力先・前処理と併用できません')
        from .preflight import inspect_document
        inspected = []
        try:
            if args.pages is not None and not args.pages.strip():
                raise ConversionError('対象ページを指定してください（all または 1,3-5）')
            if args.report and (not args.report.parent.is_dir() or any(paths_conflict(args.report, p) for p in [*args.inputs,*([args.password_file] if args.password_file else [])])):
                raise ConversionError('レポートの保存先が不正です')
            if args.report and args.report.is_dir():
                raise ConversionError('レポートの保存先がファイルではなくフォルダーです')
            if args.report and os.path.lexists(args.report) and not args.overwrite:
                raise ConversionError(f'Report already exists: {args.report}')
            for source in args.inputs:
                with pikepdf.open(source, password=password or '') as pdf:
                    numbers = [args.page] if args.page else select_pages(args.pages or 'all', len(pdf.pages))
                if args.combine:
                    from .preflight import inspect_combination
                    inspected.extend(inspect_combination(source, numbers, args.raster_dpi, raster_fallback=not args.strict,
                        password=password, flatten_annotations=args.flatten_annotations))
                else:
                    inspected.extend(inspect_document(source, numbers, args.raster_dpi,
                        password=password, flatten_annotations=args.flatten_annotations))
            if args.report: publish_report(args.report, inspected, overwrite=args.overwrite)
        except (ConversionError, pikepdf.PdfError, pikepdf.PasswordError, OSError) as error:
            print(f'ERROR: {error}', file=sys.stderr)
            return 1
        print(json.dumps(inspected, ensure_ascii=False, indent=2))
        return int(any(not r['native_supported'] or r.get('combined_blocker') for r in inspected))
    plans = []
    try:
        if not math.isfinite(args.raster_dpi) or not 72 <= args.raster_dpi <= 1200:
            raise ConversionError('Raster DPI must be between 72 and 1200')
        if args.pages is not None and not args.pages.strip():
            raise ConversionError('対象ページを指定してください（all または 1,3-5）')
        for source in args.inputs:
            if source.suffix.lower() != '.pdf':
                raise ConversionError('Input must have a .pdf extension')
            base = args.output or ((args.output_dir or source.parent)/(source.stem+'.ai'))
            if base.suffix.lower() != '.ai':
                raise ConversionError('Output must have an .ai extension')
            if args.pages or args.combine:
                with pikepdf.open(source, password=password or '') as pdf:
                    selected = select_pages(args.pages or 'all', len(pdf.pages))
                if args.combine:
                    plans.append((source, base, selected))
                else:
                    plans.extend((source, base.with_name(f'{base.stem}_{number:03d}.ai'), number) for number in selected)
            else:
                plans.append((source, base, args.page))
        for _, out, _ in plans:
            if out.suffix.lower() != '.ai' or not out.parent.is_dir():
                raise ConversionError('出力先フォルダーと .ai 拡張子を確認してください')
            if out.exists() and not args.overwrite:
                raise ConversionError(f'Output already exists: {out}')
            if out.is_dir():
                raise ConversionError(f'出力先がファイルではなくフォルダーです: {out}')
        if duplicate_destinations([out for _, out, _ in plans]):
            raise ConversionError('複数入力の出力名が衝突しています')
        if any(paths_conflict(out, source) for _, out, _ in plans for source in args.inputs):
            raise ConversionError('出力先が入力ファイルと衝突しています')
        if args.password_file and any(paths_conflict(out,args.password_file) for _,out,_ in plans):
            raise ConversionError('出力先がパスワードファイルと衝突しています')
        if args.report:
            if any(paths_conflict(args.report, p) for p in args.inputs):
                raise ConversionError('report path conflicts with input/output')
            if args.password_file and paths_conflict(args.report,args.password_file):
                raise ConversionError('レポートの保存先がパスワードファイルと衝突しています')
            if not args.report.parent.is_dir():
                raise ConversionError('レポートの保存先フォルダーが存在しません')
            if args.report.is_dir():
                raise ConversionError('レポートの保存先がファイルではなくフォルダーです')
            if os.path.lexists(args.report) and not args.overwrite:
                raise ConversionError(f'Report already exists: {args.report}')
            if duplicate_destinations([*(out for _, out, _ in plans), args.report]):
                raise ConversionError('report path conflicts with input/output')
    except (ConversionError, pikepdf.PdfError, pikepdf.PasswordError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    from .batch_publish import publish_batch
    results = []
    messages = []
    try:
        # Stage each destination on its own filesystem, including the report.
        # No output becomes visible before every conversion has succeeded.
        with ExitStack() as stack:
            directories = {}
            def staged_path(destination):
                parent = destination.parent.resolve()
                if parent not in directories:
                    directories[parent] = Path(stack.enter_context(tempfile.TemporaryDirectory(
                        prefix='.pdf2ai-cli-', dir=parent)))
                return directories[parent]/destination.name
            files = []
            for source, output, selected in plans:
                staged = staged_path(output)
                worker_result = None
                if args.timeout:
                    from .worker import run_conversion
                    request = dict(source=str(source),output=str(staged),combined=args.combine,
                        raster_fallback=not args.strict,raster_dpi=args.raster_dpi,
                        outline_text=args.outline_text,ghostscript=args.ghostscript,
                        password=password,flatten_annotations=args.flatten_annotations)
                    request['pages' if args.combine else 'page_number'] = selected
                    worker_result = run_conversion(request,args.timeout)
                if args.combine:
                    batch = worker_result if worker_result is not None else convert_document(source, staged, pages=selected,
                        raster_fallback=not args.strict, raster_dpi=args.raster_dpi,
                        outline_text=args.outline_text, ghostscript=args.ghostscript,
                        password=password, flatten_annotations=args.flatten_annotations)
                    for item in batch:
                        item['output'] = str(output)
                    results.extend(batch)
                    messages.append(f'{output}: {len(batch)} artboards')
                else:
                    item = worker_result if worker_result is not None else convert(source, staged, page_number=selected,
                        outline_text=args.outline_text, ghostscript=args.ghostscript,
                        raster_fallback=not args.strict, raster_dpi=args.raster_dpi,
                        password=password, flatten_annotations=args.flatten_annotations)
                    item['output'] = str(output)
                    results.append(item)
                    messages.append(f"{output}: {item['subpaths']} subpaths, {len(item['spots'])} spot colors, {item['images']} images")
                files.append((staged, output))
            if args.report:
                staged_report = staged_path(args.report)
                publish_report(staged_report, results)
                files.append((staged_report, args.report))
            publish_batch(files, overwrite=args.overwrite)
    except subprocess.TimeoutExpired:
        print('ERROR: 変換が制限時間を超えました。AI・レポートは保存していません。',file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('変換を中止しました。保存済みの出力は復元しています。',file=sys.stderr)
        return 130
    except (ValueError, pikepdf.PdfError, pikepdf.PasswordError, OSError, RuntimeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    for item in results:
        if item['rasterized']:
            print(f"IMAGE FALLBACK: {item['output']}: page {item['page']}: {item['fallback_reason']}", file=sys.stderr)
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
