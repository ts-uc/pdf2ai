"""English and Japanese messages, shared by the CLI and Scribus bridge.

The core API retains Japanese defaults for existing callers. Front ends select
English explicitly, or Japanese when Scribus reports a Japanese UI locale.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial

_language = ContextVar('pdf2ai_language', default='ja')


def normalize_language(value):
    return 'ja' if str(value or '').strip().lower().replace('-', '_').split('_')[0] == 'ja' else 'en'


def get_language():
    return _language.get()


def set_language(value):
    _language.set(normalize_language(value))


@contextmanager
def use_language(value):
    token = _language.set(normalize_language(value))
    try:
        yield
    finally:
        _language.reset(token)


def tr(message, *, language=None, **values):
    selected = get_language() if language is None else normalize_language(language)
    template = MESSAGES.get(message, message) if selected == 'en' else message
    return template.format(**values) if values else template


def translator(language=None):
    return partial(tr, language=get_language() if language is None else normalize_language(language))


MESSAGES = {'1つのAIファイル（{v0}）':'One AI file ({v0})','表示言語（既定：英語）':'Display language (default: English)','--checkは出力先・前処理と併用できません': '--check cannot be combined with output paths or text preprocessing',
 '--outputは入力1件で使用してください': '--output requires exactly one input',
 '--pageと--pages/--combineは併用できません': '--page cannot be combined with --pages or --combine',
 '--pageは1以上にしてください': '--page must be at least 1',
 '1つのAIにまとめられるページ数は1〜1000です。': 'A combined AI must contain between 1 and 1000 pages.',
 '1つのAIファイル（': 'One AI file (',
 'AIを作らず全ページのベクター対応可否を検査': 'Check vector support without creating AI files',
 'AI書き出し': 'AI Export',
 'AI書き出し：PDFを作成しています…': 'AI Export: creating PDF…',
 'AI書き出し：PDF作成': 'AI Export: Create PDF',
 'AI書き出し：{}ページを変換しています…': 'AI Export: converting {} pages…',
 'AI書き出し：エラー': 'AI Export: Error',
 'AI書き出し：上書き': 'AI Export: Overwrite',
 'AI書き出し：保存先': 'AI Export: Save As',
 'AI書き出し：書き出し前チェック': 'AI Export: Preflight',
 'ERROR: パスワードを読み取れませんでした: {v0}': 'ERROR: Could not read the password: {v0}',
 'ERROR: 変換が制限時間を超えました。AI・レポートは保存していません。': 'ERROR: Conversion timed out. No AI files or report were '
                                           'saved.',
 'ERROR: 変換の制限時間は0以上の有限秒数で指定してください。': 'ERROR: The timeout must be a finite number of seconds, 0 or '
                                      'greater.',
 'Ghostscriptで文字をアウトライン化して取り込む': 'Outline text using Ghostscript before conversion',
 'Ghostscript実行ファイルのパス': 'Path to the Ghostscript executable',
 'JSONログを出力する': 'Write a JSON report',
 'PDFに変換対象ページがありません': 'The PDF has no pages to convert',
 'PDFのパスと特色からIllustrator 2020編集データを生成する実験的ツール': 'Convert PDF paths and spot colors to Illustrator '
                                                'CC2020 editable AI files',
 'PDFパスワードをUTF-8ファイルの先頭行から読む': 'Read the PDF password from the first line of a UTF-8 file',
 'PDFパスワードを非表示で入力': 'Prompt for the PDF password without displaying it',
 'PDF作成が制限時間を超えたため中止しました。AIは保存していません。': 'PDF creation timed out. No AI files were saved.',
 'PDF作成の進捗画面が終了しました。AI変換は開始していません。': 'The PDF progress window closed. AI conversion has not started.',
 'PDF作成の進捗画面を開始できませんでした。': 'Could not start the PDF progress window.',
 'PDF作成後に中止しました。AIは保存していません。': 'Export cancelled after PDF creation. No AI files were saved.',
 'ScribusでPDFを作成しています。中止は現在のPDF作成が終わった時点で反映します。': 'Scribus is creating the PDF. Cancellation takes '
                                                  'effect when PDF creation finishes.',
 'ScribusのPDFページ数が対象ページ数と一致しません。': 'The exported PDF page count does not match the selected Scribus '
                                   'pages.',
 'ScribusのPDF書き出しが完了しませんでした。': 'Scribus did not finish exporting the PDF.',
 'Scribus：AI書き出し': 'Scribus: AI Export',
 '[デフォルト]': '[Default]',
 '[レジストレーション]': '[Registration]',
 'all または 1,3-5。既定はページ別出力': 'all or 1,3-5; creates separate AI files by default',
 '{}件の既存ファイルを上書きしますか？\n{}': 'Overwrite {} existing files?\n{}',
 'このスクリプトはScribusの「スクリプトを実行」から起動してください。': 'Run this script from Script > Execute Script in Scribus.',
 'アートボード 1': 'Artboard 1',
 'キャンセル': 'Cancel',
 'トンボを付ける': 'Add crop marks',
 'パスワード入力を中止しました。': 'Password entry cancelled.',
 'ベクター変換可能': 'Vector conversion supported',
 'ページ {v0}': 'Page {v0}',
 'ページ{v0}の透明グループ色空間が結合AIと異なります。ページ別出力を選択してください。': 'Page {v0}: the transparency group color space '
                                                  'differs from the combined AI. Export separate files.',
 'ページ{v0}：': 'Page {v0}: ',
 'ページ{v0}：{v1}': 'Page {v0}: {v1}',
 'ページ{}：{}': 'Page {}: {}',
 'ページがAIキャンバスに収まりません。ページ別出力を選択してください。': 'The page does not fit the Illustrator canvas. Export separate '
                                        'files.',
 'ページ別のAIファイル': 'Separate AI files per page',
 'ページ指定は all または 1,3-5 の形式で、重複なく指定してください': 'Select pages using all or 1,3-5, without duplicates',
 'ページ番号は all / current / 1,3-5 の形式で入力してください。': 'Enter pages as all, current, or 1,3-5.',
 'ページ番号は1〜{}の範囲で入力してください。': 'Page numbers must be between 1 and {}.',
 'ページ間で特色「{v0}」の定義が異なります。ページ別出力を選択してください。': 'The spot color "{v0}" has conflicting definitions across '
                                            'pages. Export separate files.',
 'レイヤー 1': 'Layer 1',
 'レポートの保存先がパスワードファイルと衝突しています': 'The report path conflicts with the password file',
 'レポートの保存先がファイルではなくフォルダーです': 'The report destination is a directory, not a file',
 'レポートの保存先が不正です': 'Invalid report destination',
 'レポートの保存先フォルダーが存在しません': 'The report destination directory does not exist',
 'レポート：': 'Report: ',
 '一部の変換に失敗したため、AIは一式を公開していません。既存AIを保持します。': 'Some conversions failed. No AI files were published; '
                                            'existing AI files were kept.',
 '中止を受け付けました。PDF作成の終了を待っています。': 'Cancellation requested. Waiting for PDF creation to finish.',
 '中止を要求': 'Request cancellation',
 '保存先': 'Save to',
 '保存先を指定してください。': 'Select an output filename.',
 '保存：{} / 保存済み{}ページ': 'Saved to: {} / {} pages saved',
 '入力PDF（複数指定可）': 'Input PDF files',
 '全ページがAIキャンバスに収まりません。対象ページを減らすか、ページ別出力を選択してください。': 'The selected pages do not fit the Illustrator '
                                                    'canvas. Select fewer pages or export separate '
                                                    'files.',
 '出力AI（入力が1件の場合）': 'Output AI filename (one input only)',
 '出力が既に存在します: ': 'Output already exists: ',
 '出力が既に存在します: {v0}': 'Output already exists: {v0}',
 '出力の復元に失敗しました。バックアップを保持しています: ': 'Could not restore the previous output. Backups were retained at: ',
 '出力ファイルの拡張子は .ai にしてください。': 'The output filename must have an .ai extension.',
 '出力ファイルを保存しています。保存・復元の完了を待っています。': 'Saving output files. Waiting for saving or recovery to finish.',
 '出力先がパスワードファイルと衝突しています': 'The output path conflicts with the password file',
 '出力先がファイルではなくフォルダーです: {v0}': 'The output destination is a directory, not a file: {v0}',
 '出力先がファイルではなくフォルダーです。保存先を変更してください。': 'The output destination is a directory. Select a filename '
                                      'instead.',
 '出力先が入力ファイルと衝突しています': 'The output path conflicts with an input file',
 '出力先ディレクトリ': 'Output directory',
 '出力先フォルダーが存在しません。': 'The output directory does not exist.',
 '出力先フォルダーと .ai 拡張子を確認してください': 'Check the output directory and the .ai extension',
 '出力先フォルダーと .ai 拡張子を確認してください。': 'Check the output directory and the .ai extension.',
 '出力公開の確認を受け取れませんでした。AIは公開していません。': 'Output publication was not approved in time. No AI files were '
                                    'published.',
 '初期設定のスウォッチグループ': 'Default Swatch Group',
 '制限時間を超えたため停止しました。AIは公開していません。': 'Export timed out. No AI files were published.',
 '制限時間を超えました。PDF作成の終了を待って中止します。': 'Time limit exceeded. Waiting for PDF creation to finish before '
                                  'cancelling.',
 '参照…': 'Browse…',
 '各AI変換の制限秒数（0は制限なし）。超過時は一式を保存せず停止': 'Conversion timeout in seconds (0 disables the limit); no files '
                                     'are published on timeout',
 '各ページの最初の未対応理由を表示します。': 'Only the first unsupported feature on each page is listed. ',
 '変換を中止しました。保存済みの出力は復元しています。': 'Conversion cancelled. Previously saved output files are being restored.',
 '変換を停止しています。AIは公開しません。': 'Stopping conversion. No AI files will be published.',
 '変換を開始します。': 'Starting conversion.',
 '変換中：{v0}/{v1}ページ（出力AIはまだ保存していません）': 'Converting: {v0}/{v1} pages (output AI files have not been saved '
                                      'yet)',
 '変換処理を開始できませんでした。': 'Could not start conversion.',
 '変換用Pythonまたは設定画面のパッケージを見つけられません。READMEの手順でプロジェクト内に.venvを作成し、pip install ".[scribus]"を実行してください。別の環境を使う場合はPDF2AI_PYTHONにPython実行ファイルのパスを設定してください。': 'Could '
                                                                                                                                                    'not '
                                                                                                                                                    'find '
                                                                                                                                                    'the '
                                                                                                                                                    'conversion '
                                                                                                                                                    'Python '
                                                                                                                                                    'environment '
                                                                                                                                                    'or '
                                                                                                                                                    'UI '
                                                                                                                                                    'packages. '
                                                                                                                                                    'Create '
                                                                                                                                                    '.venv '
                                                                                                                                                    'in '
                                                                                                                                                    'the '
                                                                                                                                                    'project '
                                                                                                                                                    'folder '
                                                                                                                                                    'and '
                                                                                                                                                    'run '
                                                                                                                                                    'pip '
                                                                                                                                                    'install '
                                                                                                                                                    '".[scribus]" '
                                                                                                                                                    'as '
                                                                                                                                                    'described '
                                                                                                                                                    'in '
                                                                                                                                                    'README.md. '
                                                                                                                                                    'To '
                                                                                                                                                    'use '
                                                                                                                                                    'another '
                                                                                                                                                    'environment, '
                                                                                                                                                    'set '
                                                                                                                                                    'PDF2AI_PYTHON '
                                                                                                                                                    'to '
                                                                                                                                                    'its '
                                                                                                                                                    'Python '
                                                                                                                                                    'executable.',
 '対象 {v0}ページ／画像化が必要 {v1}ページ': 'Selected: {v0} pages / Rasterization required: {v1} pages',
 '対象ページを1つのAIファイルにまとめる': 'Combine selected pages into one AI file',
 '対象ページを指定してください。': 'Select at least one page.',
 '対象ページを指定してください（all または 1,3-5）': 'Select pages using all or 1,3-5',
 '対象ページ：all（全ページ） / current（現在） / 例：1,3-5': 'Pages: all / current / e.g. 1,3-5',
 '文書の裁ち落としを含める': 'Include document bleeds',
 '既存出力を上書き': 'Overwrite existing output files',
 '書き出し': 'Export',
 '書き出しをキャンセルしました。AIは公開していません。': 'Export cancelled. No AI files were published.',
 '書き出し前チェックを開始します。': 'Starting preflight.',
 '書き出し前チェック：{v0}/{v1}ページ': 'Preflight: {v0}/{v1} pages',
 '書き出し方法': 'Export mode',
 '書き出し方法は combined / separate のいずれかを指定してください。': 'Export mode must be combined or separate.',
 '書き出し方法：': 'Export mode: ',
 '書き出す文書を開いてください。': 'Open the document you want to export.',
 '未対応機能があれば画像化せずエラーにする': 'Fail on unsupported features instead of rasterizing',
 '未対応機能を画像化せずエラーにする': 'Reject unsupported features instead of rasterizing pages',
 '検査で書き出しを妨げる条件が見つかりました。上の詳細を確認してください。': 'Preflight found conditions that prevent export. Review the '
                                         'details above.',
 '検査・変換の制限時間（各処理／分。0は制限なし）': 'Preflight/conversion time limit (minutes per operation; 0 disables the '
                             'limit)',
 '注釈・フォームの外観を通常の図形に取り込む（対話機能は失われる）': 'Flatten annotation and form appearances (interactive behavior is '
                                     'not retained)',
 '画像化が必要：': 'Rasterization required: ',
 '画像化したページでは文字・パス・特色・レイヤーの個別編集が失われます。': 'Rasterized pages lose individually editable text, paths, spot '
                                        'colors, and layers.',
 '画像化したページは文字・パス・特色・レイヤーを個別に再編集できません。': 'Text, paths, spot colors, and layers on rasterized pages '
                                        'cannot be edited individually.',
 '画像化したページ：': 'Rasterized pages: ',
 '画像化する場合の解像度（dpi）': 'Rasterization resolution (dpi)',
 '結合できません：': 'Cannot combine pages: ',
 '結合の配置・色空間・特色定義も検査済みです。': 'Combined layout, color space, and spot definitions have also been checked.',
 '結果をJSONで保存': 'Write conversion results as JSON',
 '自動画像化の解像度（72〜1200、既定300dpi）': 'Raster fallback resolution (72–1200 dpi; default: 300)',
 '複数ページPDFの対象ページ（1から）': 'Page to convert from a multipage PDF (starting at 1)',
 '複数入力の出力名が衝突しています': 'Multiple inputs have conflicting output filenames',
 '設定画面を開始できませんでした。': 'Could not open the export settings window.',
 '選択ページを1つのAIにまとめる（既定は全ページ）': 'Combine selected pages into one AI file (all pages by default)'}
