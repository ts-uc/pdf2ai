# PDF2AI

Export Scribus documents or convert PDFs to AI files without Illustrator. Runs on Windows, macOS, and GNU/Linux.

Illustrator を使わず、Scribus 文書や PDF から CC2020 形式の AI ファイルを作成します。Windows・macOS・GNU/Linux に対応しています。

## Scribus: setup / セットアップ

Install **Scribus 1.6 or later with Scripter enabled** and **Python 3.10 or later**. Open a terminal in this project's root directory (the directory containing this README), then run the commands for your OS.

**Scripter が有効な Scribus 1.6 以降**と**Python 3.10 以降**を用意してください。この README があるプロジェクトのルートで、OS に応じたコマンドを実行します。

**Windows (PowerShell)**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

**macOS ・ GNU/Linux**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
```

Keep `integrations/scribus/export_ai.py` in its current location. The script uses the project's `.venv`; no additional packages are needed inside Scribus's Python.

`integrations/scribus/export_ai.py`は現在の場所に置いたまま使ってください。プロジェクトの`.venv`を使うため、Scribus 内の Python への追加パッケージのインストールは不要です。

## Scribus: export / 書き出し

1. Open your document in Scribus. / Scribus で文書を開きます。
2. Choose **Script → Execute Script** and select [`integrations/scribus/export_ai.py`](integrations/scribus/export_ai.py). / **スクリプト → スクリプトを実行**から同ファイルを選びます。
3. Enter `all`, `current`, or a page selection such as `1,3-5`. / `all`（全ページ）、`current`（現在のページ）、`1,3-5`（指定ページ）のいずれかを入力します。
4. Choose the output folder and AI filename. / 保存先と AI ファイル名を指定します。

Each page becomes a separate AI file. Multiple pages use the original page numbers, such as `design_001.ai`. A `design.report.json` file records the results. Existing outputs require overwrite confirmation. You can run the script again from Scribus's recent scripts.

1 ページにつき 1 つの AI ファイルを出力します。複数ページは`design_001.ai`のように元のページ番号を付け、結果を`design.report.json`に保存します。既存ファイルがある場合は上書きを確認します。次回からは Scribus の最近使ったスクリプトから実行できます。

For DIC colors, mark them as **spot colors** in Scribus. Names such as `DIC 1` and `DIC 4` automatically map to the supplied Lab swatches `DIC 1s` and `DIC 4s*`.

DIC 色は Scribus で**特色**として登録してください。`DIC 1`や`DIC 4`も、同梱の Lab スウォッチ`DIC 1s`や`DIC 4s*`に自動で割り当てます。

**Experimental:** text is outlined, and unsupported features cause the entire page to be rasterized. Check the completion message, report, and output before submitting artwork.

**実験的なツールです。** 文字はパス化し、未対応機能があるページはページ全体を画像化します。入稿前に完了メッセージ・レポート・出力内容を確認してください。

## Direct PDF conversion / スクリプトから直接変換

After the setup above, run the launcher from the project root. Scribus is not required for this method.

上記のセットアップ後、プロジェクトのルートからランチャーを実行します。この方法では Scribus は不要です。

**Windows (PowerShell)**

```powershell
.\.venv\Scripts\python.exe run_pdf2ai.py input.pdf -o output.ai
```

**macOS ・ GNU/Linux**

```sh
.venv/bin/python run_pdf2ai.py input.pdf -o output.ai
```

For multipage PDFs, add `--page 2` to select a page. Add `--gui` instead of the input/output arguments to launch the desktop interface (requires Tkinter).

複数ページ PDF は`--page 2`などで対象ページを指定します。入出力の引数の代わりに`--gui`を指定すると、デスクトップ画面を起動します（Tkinter が必要です）。

See [technical details](docs/technical.md) for advanced options, supported features, limitations, troubleshooting, testing, and packaging.

詳細な設定、対応機能・制限、トラブル時の設定、検証・配布手順は[技術詳細](docs/technical.md)を参照してください。
