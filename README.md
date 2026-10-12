# PDF2AI：Scribus・PDFからIllustratorのAIファイルへ変換

**PDF2AIは、Scribus文書やPDFをAdobe Illustrator CC2020形式のAIファイルへ書き出すツールです。** 変換時にIllustratorは不要です。対応する図形は編集できるベクターとして出力し、DIC・東洋インキ（TOYO）の特色にも対応しています。

Scribusからは設定画面で書き出せます。既存のPDFは、ターミナルからコマンドを実行して変換します。Windows・macOS・GNU/Linux向けに提供しています。現在のバージョンは **1.0.0** です。

PDF2AI converts Scribus documents and PDF files to Adobe Illustrator CC2020 AI files without requiring Illustrator for conversion. It supports editable vector paths, multiple artboards, and DIC / TOYO spot colors. Text is outlined; unsupported pages are rasterized unless strict mode is enabled.

> 文字はアウトラインになり、文字としての再編集はできません。未対応機能を含むページは、初期設定ではページ全体を画像に変換します。対応範囲には制限があるため、入稿前に出力内容を確認してください。

## PDF2AIでできること

- **ScribusからAIを書き出す**：対象ページ・保存先・書き出し方法を画面で選択できます。
- **PDFをAIへ変換する**：対応するパス・画像・グラデーション・レイヤーを取り込みます。
- **複数ページを扱う**：ページ別のAIに保存するか、一つのAIの複数アートボードにまとめられます。
- **DIC・TOYOの特色を保持する**：ベクター変換できるページでは、特色名と塗り・線の濃度を保持します。
- **書き出し前に確認する**：ベクター対応可否の検査、画像化を禁止する設定、JSONログの出力に対応しています。

## 動作環境

| 用途 | 必要なもの |
| --- | --- |
| PDFを直接変換 | Python 3.10以降 |
| Scribusから書き出し | Python 3.10以降と、Scripterが有効なScribus 1.6以降 |
| 追加の文字アウトライン前処理 | Ghostscript。通常の変換には必須ではありません |

必要なPythonパッケージは、次のインストール手順でまとめて導入できます。出力形式はIllustrator CC2020を対象にしています。別のIllustratorバージョンや制作・印刷環境での結果は、実際の出力で確認してください。

## インストール：初回だけの準備

リポジトリをダウンロードして展開し、**このREADMEがあるフォルダー**でターミナルを開いてください。OSに合わせて、次の2行を実行します。

### Windows（PowerShell）

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[scribus]"
```

### macOS・GNU/Linux

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ".[scribus]"
```

この手順で、変換処理とScribusの設定画面に必要なパッケージが入ります。**PDFのコマンドライン変換だけを使う場合は、2行目の `".[scribus]"` を `"."` に置き換えられます。**

準備が終わったら、以下のどちらかの方法で変換してください。Scribus連携を使う場合は、ダウンロードしたフォルダーの構成を保ち、スクリプトを元の場所から実行します。

## ScribusからIllustrator形式のAIを書き出す

1. 書き出したい文書をScribusで開きます。
2. **スクリプト → スクリプトを実行**（Script → Execute Script）から、[`integrations/scribus/export_ai.py`](integrations/scribus/export_ai.py) を選びます。
3. **対象ページ**を指定します。全ページは `all`、現在のページは `current`、範囲指定は `1,3-5` のように入力します。
4. **書き出し方法**と**保存先**を選び、**書き出し**を押します。
5. 書き出し前チェックで警告が出た場合は、内容を確認して進めます。警告がなければ、そのまま変換が始まります。

### ページ別出力と複数アートボードの違い

| 書き出し方法 | 出力結果 |
| --- | --- |
| ページ別のAIファイル（初期設定） | 各ページを別のAIに保存。複数ページなら `design_001.ai` など、元のページ番号が付きます |
| 対象ページを1つのAIファイルにまとめる | 選択したページを独立したアートボードとして、一つの `design.ai` に保存します |

ベクターの編集性を優先する場合は、**未対応機能があれば画像化せずエラーにする**を有効にしてください。未対応ページがあると、画像化して書き出す代わりに停止します。

設定画面では、画像化する場合の解像度、JSONログ、制限時間、裁ち落とし、トンボも指定できます。PDF作成・検査・変換の進捗画面からキャンセルできますが、ScribusのPDF作成中は完了待ちになります。

全ページの変換が成功してから、AIを一式保存します。途中の変換失敗やキャンセルでは既存AIを保持し、保存中の通常のエラーでは元のファイルへ復元します。保存・復元中はキャンセルできません。詳しくは[Scribus書き出しの保存・キャンセル仕様](docs/scribus-export-safety.md)を参照してください。

## PDFをAIファイルへ変換する（コマンドライン）

インストール後、このREADMEがあるフォルダーで実行します。`input.pdf` を入力PDF、`output.ai` を保存先に置き換えてください。パスに空白がある場合は、`"My Design.pdf"` のように引用符で囲みます。

### Windows（PowerShell）

```powershell
.\.venv\Scripts\python.exe run_pdf2ai.py input.pdf -o output.ai
```

### macOS・GNU/Linux

```sh
.venv/bin/python run_pdf2ai.py input.pdf -o output.ai
```

上のコマンドは1ページのPDF用です。複数ページのPDFでは、次のオプションで対象と保存方法を指定します。オプションはWindowsでも共通です。

| 目的 | 追加するオプション | 結果 |
| --- | --- | --- |
| 2ページ目だけを変換 | `--page 2` | 指定した `output.ai` に保存 |
| 全ページを別々に保存 | `--pages all` | `output_001.ai` などに保存 |
| 指定ページを別々に保存 | `--pages 1,3-5` | 元のページ番号を付けて保存 |
| 全ページを一つのAIに結合 | `--combine` | 各ページをアートボードにして保存 |
| 指定ページだけを結合 | `--combine --pages 1,3-5` | 選択したページを一つのAIに保存 |
| 未対応ページの画像化を禁止 | `--strict` | 未対応機能があればエラー |
| 結果をJSONに保存 | `--report result.json` | AIと変換結果を一括保存 |
| 既存出力の上書きを許可 | `--overwrite` | 既存AI・指定したレポートを上書き |

たとえば、全ページを一つのAIにまとめる場合は次のように実行します。

```sh
.venv/bin/python run_pdf2ai.py input.pdf --combine -o output.ai
```

### AIを作らずに対応可否を確認する

```sh
.venv/bin/python run_pdf2ai.py input.pdf --check
```

Windowsでは、冒頭の `.venv/bin/python` を `.\.venv\Scripts\python.exe` に置き換えてください。

結合の配置・色空間の条件も調べる場合は `--check --combine` を使います。各ページの最初の未対応理由を表示する検査で、すべての問題や印刷品質を保証するものではありません。

ほかに、`--ask-password`／`--password-file` による暗号化PDFの読み込み、`--flatten-annotations` による注釈・フォームの外観取り込み、`--timeout 秒` による変換時間の制限に対応しています。詳しくは[CLIオプションと対応形式](docs/technical.md)を参照してください。

## DIC・東洋インキ（TOYO）の特色を使う

Scribusの色設定で、必要なパレットをインポートし、**特色として**使用してください。DICとTOYOの色データ・パレットは独立しています。TOYOのパレットは、新旧カラーブック別に用意しています。

| パレット | 色数 | 受け付ける色名の例 | AIの特色スウォッチ |
| --- | ---: | --- | --- |
| [DIC Lab](integrations/scribus/palettes/DIC_Lab.xml) | 1280 | `DIC 1`、`DIC 1s`、`DIC 4` | 旧版DICカラーブックのCMYK代替値 |
| [TOYO COLOR FINDER Lab](integrations/scribus/palettes/TOYO_COLOR_FINDER_Lab.xml) | 1079 | `CF 10001`、`CF10001` | 対応するLab特色 |
| [TOYO 94 Lab](integrations/scribus/palettes/TOYO_94_Lab.xml) | 1050 | `TOYO 0001`、`TOYO 1` | 対応するLab特色 |

DICのパレットはLab値を使いますが、登録済みDIC名のAI出力はCMYK基準へそろえます。TOYOはLabを使い、対応するLab入力の実際の値を保持します。TOYOの新旧カラーブックは別々に扱います。

ベクター変換できるページでは、特色名と塗り・線の濃度を保持し、特色をプロセスカラーへ分解しません。**ページが画像化された場合は、特色分版とパスの編集性が失われます。** 特色を残す必要があるときは、Scribusの画像化禁止設定またはCLIの `--strict` を使ってください。

プロセスカラーへ変換済みの図形から、名前だけで元の特色を復元する機能はありません。収録色・色名・代替値の詳しい説明は、[DIC特色の出力仕様](docs/dic-cmyk-reference.md)と[東洋インキの特色対応](docs/toyo-spot-colors.md)を参照してください。

## よくある質問・困ったとき

### Illustratorをインストールする必要はありますか？

通常の変換にIllustratorは不要です。同梱の特色データも、そのまま利用できます。

### 変換後の文字を編集できますか？

文字はアウトラインになり、形状として編集できます。文字列・フォントとしての再編集はできません。フォントや文字表現が未対応の場合は、ページが画像化されるか、画像化禁止設定でエラーになります。

### 図形が画像になった場合はどうすればよいですか？

書き出し前チェックやJSONログで未対応理由を確認してください。編集できるベクターが必要な場合は、元文書の未対応機能を変更するか、画像化禁止設定で出力を止めます。[対応機能と制限](docs/technical.md)に詳しい一覧があります。

### Scribusで「変換用Pythonを見つけられない」と表示されます

このREADMEの初回設定を、スクリプトと同じプロジェクトフォルダーで実行したか確認してください。Scribusの設定画面を使う場合は `".[scribus]"` のインストールが必要です。別のPython環境を使う設定は[Scribus連携の詳細](docs/technical.md)を参照してください。

### 既存のAIファイルを上書きできますか？

Scribusでは上書き確認が表示されます。CLIでは、上書きする場合だけ `--overwrite` を指定してください。保存先フォルダーは、実行前に作成しておきます。

## 対応範囲と検証記録

PDF2AIは対応範囲を検証しながら開発している変換ツールです。AIとして保存できることと、あらゆるPDF・Illustratorバージョン・印刷環境で完全に再現できることは別です。色、形状、文字のアウトライン、特色分版、画像化の有無を入稿前に確認してください。

- [技術ガイド：CLI・対応機能・ファイル形式](docs/technical.md)
- [Scribusの保存・キャンセル・復元処理](docs/scribus-export-safety.md)
- [Illustrator出力との形式・描画比較](docs/ai-files-format-alignment.md)
- [v1.0.0前の最終確認：自動テスト・配布物の検証](docs/release-v1.0.0-check.md)
