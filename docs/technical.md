# Technical details / 技術詳細

[Quick start / 使用方法](../README.md)

This document contains detailed Japanese instructions for the Scribus integration, conversion features, limitations, file structure, testing, and distribution.

Scribus連携の詳細設定、変換機能と制限、ファイル構造、検証・配布の手順をまとめています。初めて使う場合はREADMEのセットアップ手順を参照してください。以下のコマンドとファイルパスはすべてプロジェクトのルートを基準にしています。

## Scribus integration / Scribus連携

`integrations/scribus/export_ai.py`をScribusのScripterから実行すると、開いている文書を直接AIに書き出せます。Scripterが有効なScribus 1.6以降を対象にしています。Scribus内のPythonに変換用パッケージをインストールする必要はありません。

最初にプロジェクトのルートで変換用の仮想環境を用意します。

```sh
python -m venv .venv
# macOS / Linux
.venv/bin/python -m pip install ".[scribus]"
# Windows
.venv\Scripts\python.exe -m pip install ".[scribus]"
```

1. Scribusで書き出す文書を開きます。未保存の編集内容も対象です。
2. **スクリプト → スクリプトを実行**から`integrations/scribus/export_ai.py`を選びます。
3. 対象ページを入力します。`all`は全ページ、`current`は現在のページ、`1,3-5`は指定ページです。
4. **書き出し方法**で「ページ別のAIファイル」または「対象ページを1つのAIファイルにまとめる」を選び、保存先とAIファイル名を指定します。初期の保存先は元の文書があるフォルダーです。未保存の文書は現在の作業フォルダーを使います。
5. 必要な場合だけ「JSONログを出力する」にチェックを入れ、「書き出し」を押します。チェックの初期値はオフです。

ページ別出力（初期設定）は、1ページなら指定した名前、複数ページなら`design_001.ai`、`design_003.ai`のように元のページ番号を付けて保存します。まとめる場合は、選択したページを順番に独立したアートボードとして1つの`design.ai`に保存します。アートボード名は「Page 1」「Page 3」など元のページ番号を使用します。寸法・向きを保ってキャンバス内に配置し、各ページのレイヤー名にはページ番号を付けます。

1つのAIには最大1000ページをまとめられますが、標準キャンバス（14400pt四方）に配置できない場合や、ページ間で同名特色の定義が異なる場合はエラーになります。その場合はページ別出力を選択してください。未対応機能の画像化は対象ページだけに適用し、ほかのページはベクターを保持します。まとめる出力で1ページでも変換に失敗した場合、AIを新規作成・上書きしません。

チェックを入れた場合だけ、結果を同じフォルダーの`design.report.json`に保存します。チェックなしでは既存のJSONログを変更せず、ログの存在による上書き確認も行いません。既存のAI、または出力を有効にしたレポートがある場合は上書きを確認します。元のSLAファイルの保存や編集内容の変更は行いません。

文字をScribus側でパス化し、特色とレイヤーを含むPDF 1.5を一時的に書き出してから変換します。画像の間引きと追加のJPEG圧縮は行いません。印刷向けの色設定を使用し、ICC色空間への書き出しは無効にします。裁ち落としとトンボを含めず、ページ寸法で書き出します。一時ファイルは保存先のサブフォルダーに作成し、処理終了時に削除します。この連携でも対応範囲は通常のPDF変換と同じです。未対応機能は標準でページ全体を300dpiのRGB画像にし、画像化したページと理由を完了画面とレポートに表示します。

初回に選んだスクリプトはScribusの最近使ったスクリプトから再実行できます。連携ファイルはプロジェクト内の位置のまま使用してください。別のPython環境を使う場合は、Scribusを起動する環境の`PDF2AI_PYTHON`にPython実行ファイルのパスを指定します。`.venv`が見つからなければPATH上の`python3`、`python`も探します。画像化を禁止する場合は連携ファイル冒頭の`STRICT = True`、解像度を変更する場合は`RASTER_DPI`を72〜1200の範囲に設定してください。

Scribusのスクリプトメニューが表示されない場合は、Scripterプラグインが有効な配布版を使用してください。ScribusのファイルメニューにAI形式を追加するC++プラグインとしてのインストールは不要です。

設定画面は外部PythonのPySide6（QtWidgets）を使用します。`pip install ".[scribus]"`で必要なパッケージをインストールできます。Scribus内のPythonには追加しません。画面のキャンセルではPDF・AI・ログを作成しません。ログの有無にかかわらず、完了画面に成功数・エラー・画像化したページを表示します。

API仕様：[Scribus PDFfile](https://gitlab.com/scribus/scribus/-/blob/master/doc/en/scripterapi-PDFfile.html)、[ScribusのダイアログAPI](https://gitlab.com/scribus/scribus/-/blob/master/doc/en/scripterapi-dialogs.html)。

## Dependencies / 依存ソフト

Python 3.10以降を用意してください。Python 3.14以降は標準のZstandard圧縮を使用し、それ以前は`zstandard`パッケージを使用します。

```sh
python -m pip install .
```

macOS/Linuxでは環境によって`python`を`python3`に、Windowsでは`py`に読み替えてください。OS共通の依存パッケージはインストール時に入ります。通常の変換にIllustrator、Scribus、Inkscape、Ghostscriptは必要ありません。対応フォントの文字パス化と自動画像化にも追加ソフトは不要です。PyMuPDFとfontToolsはPythonパッケージとして自動でインストールされます。

GUIにはTkinterが必要です。python.orgのWindows/macOS版には通常付属します。Ubuntu系Linuxでは必要に応じて`sudo apt install python3-tk`、Homebrew版Pythonでは対応する`python-tk`をインストールしてください。

## CLI and GUI options / CLI・GUIの詳細

```sh
# コマンドライン：出力名を指定
pdf2ai sample/conversion_native.pdf -o output/native.ai

# 複数ファイル（出力先ディレクトリは先に作成）
pdf2ai sample/conversion_pages.pdf sample/conversion_fallback.pdf --page 1 --output-dir output --report output/report.json

# 複数ページPDFは、対象ページを明示して1ページずつ出力
pdf2ai document.pdf --page 2 -o page2.ai

# 未対応機能を画像化せずエラーにする
pdf2ai document.pdf --page 1 -o output/document.ai --strict
# 自動画像化の解像度を指定（既定300dpi）
pdf2ai document.pdf --page 1 -o output/document.ai --raster-dpi 200

# 補助的な文字パス化の前処理（このオプションだけGhostscriptが必要）
pdf2ai text.pdf -o text.ai --outline-text
# WindowsなどでPATHにない場合は実行ファイルを指定
pdf2ai text.pdf -o text.ai --outline-text --ghostscript "C:\Program Files\gs\gs10.xx.x\bin\gswin64c.exe"

# デスクトップGUI
pdf2ai-gui
```

上記の例は`project`ディレクトリから実行してください。

既存の出力は上書きしません。上書きする場合はCLIで`--overwrite`を指定します。GUIはPDFの複数選択に対応します。

仮想環境を作成した場合は、プロジェクトのルートからランチャーを実行できます。

```sh
.venv/bin/python run_pdf2ai.py sample/conversion_native.pdf -o output/test.ai
.venv/bin/python run_pdf2ai.py --gui
```

仮想環境は各PCで`python -m venv .venv`を実行して作成し、その環境のPythonで`pip install .`を実行してください。Windowsの仮想環境のPythonは`.venv\Scripts\python.exe`です。入力サンプルは`sample/`、生成AI・検証用PDF・レポートは`output/`にまとめてあり、どちらも`project`内にあります。`project`ディレクトリだけでテストと検証を実行できます。

## Supported features and limitations / 対応機能と制限

- 塗り・線のあるベクターパス、矩形、ベジェ曲線、複合パス、偶奇塗り。
- 平行移動、拡大縮小、回転などの座標変換。線は等方変換のみ。
- DeviceCMYK、DeviceRGB、DeviceGray。
- PDFのレイヤー（OCG）：日本語名、表示・非表示、ロック、印刷状態、空レイヤー。配置Form・画像のレイヤー属性も引き継ぎます。
- 配置PDFなどのForm XObject（入れ子・個別リソース・変換行列・BBoxクリッピング）。内部のパスや画像として取り込みます。グループ全体への不透明度・描画モードは未対応です。
- ページの90/180/270度回転とUserUnitによる拡縮。
- 標準欧文フォント、埋め込みTrueType/OpenType/CFF、対応するIdentity-H CIDフォントの文字を自動でパス化。文字間隔、文字行列、文字クリッピング、レイヤーを保持します。文字としての再編集はできません。
- 8ビットのRGB/CMYK/グレー画像、1/2/4ビットのグレー画像、Indexed画像。非圧縮・Flateの16ビット画像は8ビットに変換。通常の線形Decode指定に対応します。
- 1ビットの画像ステンシルは塗り色・特色を持つ編集可能な矩形パスとして取り込みます。
- 同じサイズの8ビットグレー画像による透過マスク（線形Decode・反転を含む）、1ビットの画像マスク、8ビット画像の色キーマスク。
- 編集可能な線形・円形グラデーションの塗り（PatternType 2・ShadingType 2/3、RGB/CMYK/グレー、両端延長、線形Type 2関数または連続したType 3関数）。線形は平行移動・回転・等方／非等方拡縮・せん断・反転に対応。円形は平行移動・回転・等方拡縮に対応し、開始半径0で、焦点が終端円の内部にあるものを扱えます（中心が異なる場合も可）。直接描画の`sh`演算子にも対応。円形は指定した中心・半径のグラデーションと元形状の切り抜き、外側の終端色に分けて生成します。
- 不透明度、塗りと線で異なる不透明度、グラデーションと線の同時描画。
- Normal、Multiply、Screen、Overlay、SoftLight、HardLight、ColorDodge、ColorBurn、Darken、Lighten、Difference、Exclusion、Hue、Saturation、Color、Luminosityの16描画モード。
- 単一・複合パスのクリッピング（穴のある切り抜き）、PDFの構造タグ、ExtGState内の線スタイル。
- 非分離・非ノックアウトのRGB/CMYKページ透明グループ。
- CMYK代替色を持つSeparation特色。線形のType 2とScribusが生成する線形Type 4の濃度関数。
- 特色名、代替CMYK値、特色濃度、CMYKのオーバープリントモード1。
- 塗りだけの図形に設定された線幅0。線幅0で実際に線を描くヘアラインは未対応です。

通常の特色は元PDFの色定義とCMYK代替値を使用します。DIC特色は、同梱の1280色の色名に一致する場合、DICカラーブックのLab値を持つ特色スウォッチとしてAIの編集データに出力します。追加の設定は不要で、Scribus連携でも有効です。塗りと線の濃度を保持します。末尾の`s`や`*`を省略した名前も自動照合し、`DIC 1`は`DIC 1s`、`DIC 4`は`DIC 4s*`のように正式なスウォッチ名で出力します。同じ色の省略名と正式名は1つのスウォッチにまとめます。登録されていない名前は元のCMYK特色として扱います。DIC名が失われたプロセスCMYKからは復元できないため、ScribusではDIC色を特色として登録してください。

DIC特色のLab入力（D50、線形Type 2）と、Labを代替色に持つLab ICCプロファイル入力にも対応します。この場合は入力のLab値を保持します。JSONレポートの`spots`にはAI編集データの色空間と色値を記録します。AIのPDF表示部分は従来どおり元PDFを保持するため、元のCMYK表示とLabで編集・再保存した表示に差が出る場合があります。同梱データは`src/pdf2ai/data/dic_lab.json`にあり、Illustratorや外部のパレットファイルを実行時に必要としません。

Scribus用パレットは`integrations/scribus/palettes/DIC_Lab.xml`です。JSONの全1280色について正式名とLab値を保持し、`SPACE="Lab"`・`Spot="1"`・`Register="0"`で定義しています。CMYKへの変換は行いません。

正の指数を持つ非線形Type 2グラデーション関数は、最大256個の編集可能な色の停止点で近似します。各成分の補間誤差の目標は0.25/255以内です。近似が上限を超える場合は画像化します。

編集データとして未対応：文字として編集可能なテキスト、複雑なフォント/CMap・縦書き・Type3、開始半径が0でない円形・焦点が終端円の外部／境界にある円形・メッシュグラデーション、グラデーションの線、円形グラデーションの非等方・せん断変換、タイルパターン、図形のソフトマスク、分離・ノックアウトの透明グループ、上記DIC特色以外のLab/ICCの色空間、DeviceN、非等方変換の線、ヘアライン、注釈、複雑なレイヤー条件（OCMD・別レイヤー条件の入れ子・排他切替）、特殊なDecode/Matte、インライン画像など。

これらを検出すると、標準では**選択したページ全体**をPyMuPDFで描画し、透過を保持したRGB画像としてAIの編集部分に埋め込みます。部分的な画像化ではありません。既定は300dpiで、`--raster-dpi`は72～1200を指定できます。画像化したページの文字・パス・特色分版・レイヤー構造は編集データでは失われます。元PDFの表示データは保持します。CLIとGUIに画像化の理由を表示し、JSONレポートに`conversion_mode`、`rasterized`、`fallback_reason`、`raster_dpi`、`lost_features`を記録します。`--strict`またはGUIのチェックで画像化を禁止できます。

画像化は4,000万ピクセルまでです。上限を超える場合は解像度を下げてください。破損・暗号化PDF、範囲外のページ、極端なページ寸法、レンダラーが描画できないPDFなどは引き続きエラーになります。複数ページは`--page`で1ページずつ変換します。

追加オプション`--outline-text`はGhostscriptの`pdfwrite`と`-dNoOutputFonts`を使用します。macOSでは`brew install ghostscript`、Ubuntu系では`sudo apt install ghostscript`、WindowsではGhostscriptの配布元からインストールしてください。`gs`、`gswin64c`、`gswin32c`をPATHから探し、見つからなければCLIで`--ghostscript`を指定できます。GUIはPATHからの検出に対応します。追加のPythonパッケージは不要です。元PDFに埋め込まれていないフォントはGhostscript側で代替される場合があります。文字はベクターパスになり、画像化しません。Ghostscriptによる前処理はページ全体に適用するため、線や色にも丸めなどの差が生じる可能性があります。元PDFの表示データはそのまま保持します。[Ghostscriptの仕様](https://ghostscript.readthedocs.io/en/gs10.05.0/VectorDevices.html)を参照してください。

## Layers / レイヤー

PDFにOCG（表示を切り替えられるレイヤー）が残っている場合、追加オプションなしでIllustratorのレイヤーとして取り込みます。非表示レイヤーの図形も保持します。元PDFの表示・非表示とロック状態、Usageの印刷状態をレイヤー属性に反映します。階層は平坦化します。

描画順を保つため、同じレイヤーの図形が別レイヤーを挟んで描かれている場合は、`背景`、`背景 (2)`のように分割します。非レイヤーの図形は`PDF artwork`に配置します。元PDFがレイヤーを統合して書き出されている場合、元のIllustrator/Scribusなどのレイヤー名・区分は復元できません。

標準の文字パス化はレイヤーを保持します。レイヤー付きPDFと追加オプション`--outline-text`の併用はGhostscriptの前処理でレイヤーが失われるため、標準ではページ画像化、`--strict`ではエラーになります。複数レイヤーの表示条件を組み合わせるOCMD、別レイヤー条件の入れ子、排他表示、ズーム等による自動表示には未対応です。

統合検証用PDFのレイヤーパネルで、日本語名・非表示・ロック・非印刷・空レイヤーを確認できます。対象アプリケーションでの互換性は利用環境で確認してください。

テストの一時ファイルは`tests/.tmp/`に作成されます。検証レポートのファイルパスはプロジェクトのルートからの相対パスで保存します。

## File structure and color handling / ファイル構造と色の扱い

AIのPDF表示部分は元PDFのページ内容・リソース・OutputIntentを保持します。編集部分はPDF演算子を解釈し、パス座標と色から新規生成します。以下の構造で編集データを保存します。

- PDF 1.6コンテナ。
- ページの`PieceInfo / Illustrator / Private`。
- `ContainerVersion=12`、`CreatorVersion=24`、`RoundtripVersion=24`。
- `%AI24_ZStandard_Data`とZstandard圧縮された編集データ。
- 65,536バイトごとの`AIPrivateDataN`ブロック。

作成アプリ関連のメタデータはCC2020の表記に統一します。PDFの`Creator`とXMPの`xmp:CreatorTool`は`Adobe Illustrator 24.0 (Macintosh)`、PDFとXMPの`Producer`は`Adobe PDF library 15.00`です。これは互換用の固定表記で、実際の生成処理は本ツールが行います。元PDFのタイトル・著者情報は保持します。

画像は元のピクセル寸法で埋め込み、透過のアルファ値を保持します。JPEGを展開する際のデコーダーの差や色の丸めにより、元PDFとわずかな表示差が生じることがあります。

元PDFのCMYK OutputIntentは表示部分に保持されますが、Illustratorで編集して再保存する際の作業用カラープロファイルは完全には再現していません。開き直し・再保存による色の見え方は、Illustratorのカラー設定で変わり得ます。編集可能なベクター変換ではCMYKの数値と特色の代替値を保持します。画像化した編集データはRGB画像になります。

この出力についてPDF/Xの再認証はしていないため、PDF/X適合を断言するメタデータは削除しています。入稿先が要求するプリフライトは別途実施してください。

## Testing and distribution / 検証と配布

統合検証用のPDFは`sample/`に3ファイルあります。図版に英語の見出しと検証項目を記載しています。

| ファイル | ページ数 | 確認する内容 |
| --- | ---: | --- |
| `conversion_native.pdf` | 1 | 42パネル。パス・線スタイル・変換・RGB/CMYK/グレー・特色・オーバープリント・配置Form・クリッピング・16描画モード・不透明度・10種類のグラデーション・画像形式とマスク・標準/埋め込みフォント・文字クリッピング・レイヤー |
| `conversion_pages.pdf` | 4 | ページ回転0/90/180/270度、UserUnit=2、CropBoxの原点と寸法、RGB/CMYKページ透明グループ |
| `conversion_fallback.pdf` | 9 | ノックアウト透明グループ、ヘアライン、非等方の線、Lab、注釈、タイルパターン、非同心円グラデーション、OCMD、補間付きステンシルの自動画像化とstrict拒否 |

ページ全体に作用する属性や画像化の判定は、1ページにまとめると個別検証できないため、後者2ファイルだけ複数ページにしています。編集機能の一覧は拡大して確認する大判ページ（1720×3300pt）です。既存サンプルや`tests/`からデータを読み込まずに再生成できます。検証項目と期待結果の一覧は`sample/conversion_suite.json`にあります。

```sh
# 3ファイルを再生成し、全14ページのAIと検証レポートを作成
python tools/make_conversion_suite.py --verify
# 任意：同じPDFでGhostscript前処理も検証
python tools/make_conversion_suite.py --verify-ghostscript
# 必要なページだけ通常のCLIで変換
pdf2ai sample/conversion_native.pdf -o output/native.ai
pdf2ai sample/conversion_pages.pdf --page 2 -o output/rotation90.ai
pdf2ai sample/conversion_fallback.pdf --page 1 -o output/fallback.ai
```

生成AI・レポート・一時ファイルは`output/conversion-suite/`内に完結します。検証処理は全ページの変換モード、CC2020編集ストリーム、元PDF表示の画素一致、画像・グラデーション・特色・レイヤー属性、回転後のアートボード寸法、画像化を禁止した場合の拒否を確認します。再保存後は作業用カラープロファイルや印刷不可レイヤーにより元PDFとの表示差が出ます。対象アプリケーションでの互換性は利用環境で確認してください。

これらのPDFで描画機能を検証できます。入力パス、破損PDF、上書き防止、DPIの不正値、メモリ上限などのエラー処理には別途プログラムのテストが必要です。

```sh
python -m pip install '.[test,scribus]'
python -m pytest -q
# 統合サンプルを再生成し、全ページを検証
python tools/make_conversion_suite.py --verify
```

自動テストは、変換元とAIのPDF表示の画素一致、統合サンプルの全14ページ、特色濃度、座標変換、未対応PDFの拒否、上書き防止、編集ストリームの圧縮・展開を検証します。

Illustratorでの再保存後の表示を確認する小さなケースは`tools/make_fidelity_cases.py --run after`で生成できます。Illustratorの「その他のスクリプト」から`tools/illustrator_fidelity_check.jsx`を実行し、`python tools/compare_fidelity.py output/fidelity-check/after`で元PDFと再保存したPDFを144dpiで比較します。AIに保持した元PDFの表示だけを比較するテストと区別しています。比較画像と画素差の数値は同フォルダーに保存します。2026-10-11に回転・斜め・せん断・焦点付き円形などのグラデーション、文字の切り抜き、画像マスクを実機確認しました。RGBとCMYKの混在画像には、作業用プロファイルや再保存時の色変換に由来する可能性のある表示差が残っています。

Python不要のGUI実行ファイルを配る場合は、**配布する各OS上で**ビルドしてください。

```sh
python -m pip install '.[build]'
python -m PyInstaller --clean --noconfirm --onefile --windowed --name pdf2ai-gui --paths src --collect-data pdf2ai --collect-all pikepdf --collect-all pymupdf --collect-all fontTools --collect-all zstandard tools/gui_entry.py
```

このビルドにはPython 3.10～3.13を推奨します。Python 3.14では標準Zstandardを使うため、`--collect-all zstandard`は不要です。macOSの署名・公証やWindowsの署名は含んでいません。

参考：[AdobeのAI形式説明](https://www.adobe.com/creativecloud/file-types/image/vector/ai-file.html)、[Adobe Illustratorの保存オプション](https://helpx.adobe.com/illustrator/using/saving-artwork.html)。
