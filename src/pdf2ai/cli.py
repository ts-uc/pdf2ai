from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import pikepdf
from .native import convert
from .vector import ConversionError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PDFのパスと特色からIllustrator 2020編集データを生成する実験的ツール")
    parser.add_argument("inputs",nargs="+",type=Path,help="入力PDF（複数指定可）")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("-o","--output",type=Path,help="出力AI（入力が1件の場合）")
    destination.add_argument("--output-dir",type=Path,help="出力先ディレクトリ")
    parser.add_argument("--page",type=int,help="複数ページPDFの対象ページ（1から）")
    parser.add_argument("--outline-text",action="store_true",help="Ghostscriptで文字をアウトライン化して取り込む")
    parser.add_argument("--ghostscript",help="Ghostscript実行ファイルのパス")
    parser.add_argument("--strict",action="store_true",help="未対応機能を画像化せずエラーにする")
    parser.add_argument("--raster-dpi",type=float,default=300,help="自動画像化の解像度（72〜1200、既定300dpi）")
    parser.add_argument("--overwrite",action="store_true",help="既存出力を上書き")
    parser.add_argument("--report",type=Path,help="結果をJSONで保存")
    args = parser.parse_args(argv)
    if args.output and len(args.inputs)!=1: parser.error("--outputは入力1件で使用してください")
    if args.page is not None and args.page<1: parser.error("--pageは1以上にしてください")
    results=[]; failed=False
    for source in args.inputs:
        output = args.output or ((args.output_dir or source.parent)/(source.stem+".ai"))
        try:
            if source.suffix.lower() != ".pdf": raise ConversionError("Input must have a .pdf extension; specify output with -o")
            report=convert(source,output,page_number=args.page,overwrite=args.overwrite,outline_text=args.outline_text,ghostscript=args.ghostscript,raster_fallback=not args.strict,raster_dpi=args.raster_dpi)
        except (ConversionError,pikepdf.PdfError,OSError) as exc:
            failed=True;report={"input":str(source),"output":str(output),"error":str(exc)}
            print(f"ERROR: {source}: {exc}",file=sys.stderr)
        else:
            if report['rasterized']:
                print(f"IMAGE FALLBACK: {output}: {args.raster_dpi:g} dpi; {report['fallback_reason']}",file=sys.stderr)
            print(f"{output}: {report['subpaths']} subpaths, {len(report['spots'])} spot colors, {report['images']} images")
        results.append(report)
    if args.report:
        if args.report.resolve() in {p.resolve() for p in args.inputs} | {Path(r['output']).resolve() for r in results}:
            print("ERROR: report path conflicts with input/output",file=sys.stderr);return 1
        args.report.write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
