# PDF2AI

Create Adobe Illustrator CC2020 files from Scribus documents or PDFs without Illustrator. Available for Windows, macOS, and GNU/Linux.

Illustrator を使わずに、Scribus 文書や PDF を Adobe Illustrator CC2020 形式の AI ファイルに変換できます。Windows・macOS・GNU/Linux に対応しています。

画面からの操作はScribusの書き出し設定画面に対応しています。PDFを直接変換する場合はCLIを使用します。

## Set up for Scribus / Scribus で使う準備

You need **Scribus 1.6 or later with Scripter enabled** and **Python 3.10 or later**. Open a terminal in the folder containing this README, then run the commands below for your OS. This setup is needed only once.

**Scripter が有効な Scribus 1.6 以降**と**Python 3.10 以降**を用意してください。この README があるフォルダーでターミナルを開き、OS に応じたコマンドを実行します。初回のみ必要な準備です。

**Windows (PowerShell)**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[scribus]"
```

**macOS / GNU/Linux**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ".[scribus]"
```

Keep the downloaded project folder together; use the script from its original location.

ダウンロードしたフォルダーの構成を保ち、スクリプトは元の場所から使用してください。

## Export from Scribus / Scribus から AI を書き出す

1. Open the document you want to export in Scribus. / 書き出したい文書を Scribus で開きます。
2. Choose **Script → Execute Script** and select [`integrations/scribus/export_ai.py`](integrations/scribus/export_ai.py). / **スクリプト → スクリプトを実行**から同ファイルを選びます。
3. Choose the pages: `all` for all pages, `current` for the current page, or `1,3-5` for specific pages. / 対象ページを入力します。`all` は全ページ、`current` は現在のページ、`1,3-5` は指定ページです。
4. Choose **ページ別のAIファイル** (separate files) or **対象ページを1つのAIファイルにまとめる** (one file), select the output filename, then click **書き出し** (Export). / **書き出し方法**でページ別または1つのAIにまとめる方法を選び、保存先とファイル名を指定して**書き出し**を押します。
5. When warnings appear, review the preflight results, then click **書き出し** to proceed. If no warnings appear, export continues automatically. / 警告がある場合は**書き出し前チェック**で内容を確認して、**書き出し**を押します。警告がなければ自動で書き出しへ進みます。画像化禁止が有効で未対応ページがある場合は書き出せません。

Separate output saves each page in an AI file, with original page numbers such as `design_001.ai`. Combined output saves the selected pages as separate artboards in a single `design.ai`. Next time, you can select the script from Scribus's recent scripts.

ページ別出力では、複数ページのファイル名に`design_001.ai`のように元のページ番号が付きます。まとめる場合は、選択した各ページを独立したアートボードとして1つの`design.ai`に保存します。初期設定はページ別です。次回からは Scribus の最近使ったスクリプトから実行できます。

全ページの変換が成功してからAIを一式保存します。途中の変換失敗やキャンセルでは既存AIを保持し、保存中の通常のエラーでは元のファイルへ復元します。PDF作成後はScribus連携の進捗画面で検査・変換の状況を確認し、キャンセルできます。保存・復元中はキャンセルできません。詳しい動作と検証範囲は[対応記録](docs/scribus-export-safety.md)を参照してください。

To use DIC colors, register them as **spot colors** in Scribus. Names such as `DIC 1` and `DIC 4` are also accepted and exported as the corresponding DIC Lab swatches.

DIC 色を使う場合は、Scribus で**特色**として登録してください。`DIC 1` や `DIC 4` のような名前でも、対応する DIC の Lab スウォッチとして書き出せます。

Import the supplied [DIC palette](integrations/scribus/palettes/DIC_Lab.xml) in Scribus’s color dialog to add all 1280 colors as spot colors.

Scribus の色設定ダイアログから同梱の [DIC パレット](integrations/scribus/palettes/DIC_Lab.xml)をインポートすると、1280 色を特色として追加できます。

**Check your output before submitting artwork.** This tool is experimental. Text becomes outlines, and pages containing unsupported features become images. Check the completion message and the resulting artwork.

**入稿前に出力を確認してください。** 実験的なツールのため、文字はアウトラインになり、未対応機能を含むページは画像になります。完了メッセージと、書き出した内容を確認してください。

## Convert an existing PDF / PDF を直接変換する

After setup, run the following command from the folder containing this README. Replace `input.pdf` with your PDF and `output.ai` with the desired output filename.

セットアップ後、この README があるフォルダーで次のコマンドを実行します。`input.pdf` を変換したい PDF に、`output.ai` を保存したいファイル名に置き換えてください。

**Windows (PowerShell)**

```powershell
.\.venv\Scripts\python.exe run_pdf2ai.py input.pdf -o output.ai
```

**macOS / GNU/Linux**

```sh
.venv/bin/python run_pdf2ai.py input.pdf -o output.ai
```

For a multipage PDF, add `--page 2` to convert page 2. See [the detailed guide](docs/technical.md) for other options, supported features, and troubleshooting.

複数ページの PDF は、`--page 2` を追加すると 2 ページ目を変換できます。その他の使い方・対応機能・困ったときの設定は[詳細ガイド](docs/technical.md)を参照してください。

全ページをページ別に保存する場合は`--pages all`、1つのAIにまとめる場合は`--combine`を指定します。`--pages 1,3-5`で範囲を選択できます。`--check`はAIを作らず全ページのベクター対応可否を検査します。追加機能・検証結果と未完了事項は[課題への対応状況](docs/issue-resolution-progress.md)を参照してください。
