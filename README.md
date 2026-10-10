# PDF2AI

Create Adobe Illustrator CC2020 files from Scribus documents or PDFs without Illustrator. Available for Windows, macOS, and GNU/Linux.

Illustrator を使わずに、Scribus 文書や PDF を Adobe Illustrator CC2020 形式の AI ファイルに変換できます。Windows・macOS・GNU/Linux に対応しています。

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
4. Choose the output folder and filename, then click **書き出し** (Export). / 保存先とファイル名を指定し、**書き出し**を押します。

Each page is saved as a separate AI file. For multiple pages, filenames include the original page number, such as `design_001.ai`. Next time, you can select the script from Scribus's recent scripts.

1 ページにつき 1 つの AI ファイルを保存します。複数ページの場合は、`design_001.ai` のように元のページ番号が付きます。次回からは Scribus の最近使ったスクリプトから実行できます。

To use DIC colors, register them as **spot colors** in Scribus. Names such as `DIC 1` and `DIC 4` are also accepted and exported as the corresponding DIC Lab swatches.

DIC 色を使う場合は、Scribus で**特色**として登録してください。`DIC 1` や `DIC 4` のような名前でも、対応する DIC の Lab スウォッチとして書き出せます。

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
