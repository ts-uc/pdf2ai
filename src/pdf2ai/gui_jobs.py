"""Desktop batch processing without Tk dependencies or UI-thread access."""
import time
from pathlib import Path
import pikepdf

from .cancellation import ConversionCancelled
from .cli import publish_report, select_pages
from .multiboard import convert_document
from .native import convert
from .vector import ConversionError


def plan_jobs(sources,directory,expression,combined):
    plans = []
    directory = Path(directory)
    if not sources or not directory.is_dir():
        raise ConversionError('PDFと出力先ディレクトリを指定してください。')
    for source in map(Path,sources):
        try:
            with pikepdf.open(source) as pdf:
                if pdf.is_encrypted:
                    raise ConversionError('暗号化PDFには未対応です。暗号化されていないPDFを指定してください。')
                if not expression and not combined and len(pdf.pages)!=1:
                    raise ConversionError('複数ページPDFの対象ページを指定してください（例：all または 1,3-5）。')
                numbers = select_pages(expression or 'all',len(pdf.pages))
        except pikepdf.PasswordError as error:
            raise ConversionError(f'{source.name}: パスワード付きPDFには未対応です。暗号化されていないPDFを指定してください。') from error
        except (ValueError,OSError,pikepdf.PdfError) as error:
            raise ConversionError(f'{source.name}: {error}') from error
        if combined:
            plans.append((source,directory/(source.stem+'.ai'),numbers))
        else:
            plans.extend((source,directory/(source.stem+(f'_{number:03d}' if expression or len(numbers)>1 else '')+'.ai'),number) for number in numbers)
    outputs = [out.resolve() for _,out,_ in plans]
    if len(outputs)!=len(set(outputs)):
        raise ConversionError('入力ファイルの出力名が衝突しています。保存先を分けて変換してください。')
    if any(output.is_dir() for _,output,_ in plans):
        raise ConversionError('出力AIと同名のフォルダーがあります。保存先を変更してください。')
    return plans


def run_jobs(plans, *, combined, overwrite, strict, outline, resolution,
             cancelled, emit, report_path=None):
    """Emit log/progress/done events. Only published pages count as saved."""
    total = sum(len(selection) if combined else 1 for _,_,selection in plans)
    completed = saved = failed = 0
    reports = []
    stopped = False
    report_error = None
    worker_error = None
    started = time.monotonic()
    try:
        for source,output,selection in plans:
            count = len(selection) if combined else 1
            label = ','.join(map(str,selection)) if combined else str(selection)
            if cancelled():
                stopped = True
                break
            emit(('log',f'処理開始: {source.name}（ページ {label}）'))
            emit(('progress',completed,total,f'{source.name}：ページ {label}'))
            try:
                if combined:
                    def progress(page,done,page_total):
                        emit(('progress',completed+done,total,
                              f'{source.name}：解析 {done}/{page_total}ページ完了、AIは未保存'))
                    batch = convert_document(source,output,pages=selection,overwrite=overwrite,
                                             raster_fallback=not strict,raster_dpi=resolution,
                                             cancelled=cancelled,progress=progress)
                else:
                    batch = [convert(source,output,page_number=selection,overwrite=overwrite,
                                     outline_text=outline,raster_fallback=not strict,
                                     raster_dpi=resolution,cancelled=cancelled)]
            except ConversionCancelled:
                stopped = True
                break
            except Exception as error:
                failed += count
                reports.append({'input':str(source),'output':str(output),
                                'pages':selection if combined else [selection], 'error':str(error)})
                emit(('log',f'エラー: {source.name}（ページ {label}）: {error}'))
            else:
                reports.extend(batch)
                saved += len(batch)
                for item in batch:
                    if item['rasterized']:
                        emit(('log',f"画像化して保存（{resolution:g}dpi）: {source.name}、ページ {item['page']}: {item['fallback_reason']}"))
                emit(('log',f'保存: {output}（{len(batch)}ページ）'))
            completed += count
            emit(('progress',completed,total,f'保存済み {saved}ページ／失敗 {failed}ページ'))
        if stopped:
            reports.append({'cancelled':True,'saved_pages':saved,'failed_pages':failed,
                            'unprocessed_pages':total-saved-failed})
            emit(('log','キャンセルしました。完了済みのファイルは保持します。'))
        if report_path is not None:
            try:
                publish_report(report_path,reports)
                emit(('log',f'レポート保存: {report_path}'))
            except Exception as error:
                report_error = str(error)
                emit(('log',f'レポート保存エラー: {error}'))
    except Exception as error:
        worker_error = str(error)
        emit(('log',f'処理を続行できませんでした: {error}'))
    finally:
        # Always release the UI, including failures in conversion/report output.
        emit(('done',{'total':total,'saved':saved,'failed':failed,'cancelled':stopped,
                      'unprocessed':total-saved-failed,'report_error':report_error,
                      'worker_error':worker_error,
                      'elapsed_seconds':time.monotonic()-started}))
