from __future__ import annotations
import argparse
import json
import os
import math
import tempfile
from pathlib import Path
import sys
import pikepdf
from .native import convert
from .vector import ConversionError
from .multiboard import convert_document


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
    parser.add_argument("--strict",action="store_true",help="未対応機能を画像化せずエラーにする")
    parser.add_argument("--raster-dpi",type=float,default=300,help="自動画像化の解像度（72〜1200、既定300dpi）")
    parser.add_argument("--overwrite",action="store_true",help="既存出力を上書き")
    parser.add_argument("--report",type=Path,help="結果をJSONで保存")
    args = parser.parse_args(argv)
    if args.output and len(args.inputs)!=1: parser.error("--outputは入力1件で使用してください")
    if args.page is not None and args.page<1: parser.error("--pageは1以上にしてください")
    if args.page is not None and (args.pages is not None or args.combine): parser.error('--pageと--pages/--combineは併用できません')
    if args.combine and args.outline_text: parser.error('--combineと--outline-textは現在併用できません')
    if args.check:
        if args.output or args.output_dir or args.combine or args.outline_text:
            parser.error('--checkは出力先・結合・前処理と併用できません')
        from .preflight import inspect_document
        inspected = []
        try:
            if args.pages is not None and not args.pages.strip():
                raise ConversionError('対象ページを指定してください（all または 1,3-5）')
            if args.report and (not args.report.parent.is_dir() or args.report.resolve() in {p.resolve() for p in args.inputs}):
                raise ConversionError('レポートの保存先が不正です')
            if args.report and args.report.is_dir():
                raise ConversionError('レポートの保存先がファイルではなくフォルダーです')
            if args.report and os.path.lexists(args.report) and not args.overwrite:
                raise ConversionError(f'Report already exists: {args.report}')
            for source in args.inputs:
                with pikepdf.open(source) as pdf:
                    numbers = [args.page] if args.page else select_pages(args.pages or 'all', len(pdf.pages))
                inspected.extend(inspect_document(source, numbers, args.raster_dpi))
            if args.report: publish_report(args.report, inspected, overwrite=args.overwrite)
        except (ConversionError, pikepdf.PdfError, pikepdf.PasswordError, OSError) as error:
            print(f'ERROR: {error}', file=sys.stderr)
            return 1
        print(json.dumps(inspected, ensure_ascii=False, indent=2))
        return int(any(not r['native_supported'] for r in inspected))
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
                with pikepdf.open(source) as pdf:
                    selected = select_pages(args.pages or 'all', len(pdf.pages))
                if args.combine:
                    plans.append((source, base, selected))
                else:
                    plans.extend((source, base.with_name(f'{base.stem}_{number:03d}.ai'), number) for number in selected)
            else:
                plans.append((source, base, args.page))
        outputs = [out.resolve() for _, out, _ in plans]
        for _, out, _ in plans:
            if out.suffix.lower() != '.ai' or not out.parent.is_dir():
                raise ConversionError('出力先フォルダーと .ai 拡張子を確認してください')
            if out.exists() and not args.overwrite:
                raise ConversionError(f'Output already exists: {out}')
            if out.is_dir():
                raise ConversionError(f'出力先がファイルではなくフォルダーです: {out}')
        if len(set(outputs)) != len(outputs):
            raise ConversionError('複数入力の出力名が衝突しています')
        if set(outputs) & {p.resolve() for p in args.inputs}:
            raise ConversionError('出力先が入力ファイルと衝突しています')
        if args.report:
            if args.report.resolve() in {p.resolve() for p in args.inputs} | set(outputs):
                raise ConversionError('report path conflicts with input/output')
            if not args.report.parent.is_dir():
                raise ConversionError('レポートの保存先フォルダーが存在しません')
            if args.report.is_dir():
                raise ConversionError('レポートの保存先がファイルではなくフォルダーです')
            if os.path.lexists(args.report) and not args.overwrite:
                raise ConversionError(f'Report already exists: {args.report}')
    except (ConversionError, pikepdf.PdfError, pikepdf.PasswordError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    results=[]; failed=False
    for source, output, selected in plans:
        try:
            if source.suffix.lower() != ".pdf": raise ConversionError("Input must have a .pdf extension; specify output with -o")
            if args.combine:
                batch = convert_document(source, output, pages=selected, overwrite=args.overwrite,
                                         raster_fallback=not args.strict, raster_dpi=args.raster_dpi)
                results.extend(batch)
                for item in batch:
                    if item['rasterized']:
                        print(f"IMAGE FALLBACK: {output}: page {item['page']}: {item['fallback_reason']}", file=sys.stderr)
                print(f'{output}: {len(batch)} artboards')
                continue
            report=convert(source,output,page_number=selected,overwrite=args.overwrite,outline_text=args.outline_text,ghostscript=args.ghostscript,raster_fallback=not args.strict,raster_dpi=args.raster_dpi)
        except (ConversionError,pikepdf.PdfError,pikepdf.PasswordError,OSError) as exc:
            failed=True;report={"input":str(source),"output":str(output),"error":str(exc)}
            print(f"ERROR: {source}: {exc}",file=sys.stderr)
        else:
            if report['rasterized']:
                print(f"IMAGE FALLBACK: {output}: {args.raster_dpi:g} dpi; {report['fallback_reason']}",file=sys.stderr)
            print(f"{output}: {report['subpaths']} subpaths, {len(report['spots'])} spot colors, {report['images']} images")
        results.append(report)
    if args.report:
        try:
            publish_report(args.report, results, overwrite=args.overwrite)
        except OSError as exc:
            print(f'ERROR: レポートを保存できませんでした: {exc}', file=sys.stderr)
            return 1
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
