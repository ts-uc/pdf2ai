# PDF2AI: Convert Scribus Documents and PDFs to Illustrator AI Files

**PDF2AI exports Scribus documents and PDF files as Adobe Illustrator CC2020-compatible AI files without requiring Illustrator for conversion.** Supported artwork remains editable as vector paths, with support for multiple artboards, layers, images, gradients, and DIC / TOYO spot colors.

Use the export dialog from Scribus, or convert an existing PDF from the command line. PDF2AI supports Windows, macOS, and GNU/Linux. The current version is **1.1.0**.

> Text becomes outlines, so it cannot be edited as text. Pages containing unsupported features are rasterized by default. Use strict mode if you need to retain editable vectors or spot separations. Check the output before submitting artwork for production.

## What PDF2AI Does

- **Export AI from Scribus:** choose pages, an output filename, and the export mode in a dialog.
- **Convert PDF to AI:** import supported paths, images, gradients, and layers.
- **Export multiple pages:** save separate AI files or combine pages as artboards in one AI file.
- **Preserve DIC and TOYO spot colors:** keep spot names and fill/stroke tints on vector-converted pages.
- **Check before exporting:** inspect vector support, reject raster fallback, and optionally save a JSON report.

PDF2AIは、Illustratorを使わずにScribus文書やPDFをAIファイルへ変換するツールです。DIC・東洋インキの特色や、複数ページの書き出しに対応しています。詳しい説明は[日本語ガイド（README_ja.md）](README_ja.md)をご覧ください。

## Requirements

| Use                         | Requirements                                                        |
| --------------------------- | ------------------------------------------------------------------- |
| Convert an existing PDF     | Python 3.10 or later                                                |
| Export from Scribus         | Python 3.10 or later and Scribus 1.6 or later with Scripter enabled |
| Optional text preprocessing | Ghostscript; not required for normal conversion                     |

The installation commands below install the required Python packages. The target AI format is Illustrator CC2020. Compatibility with other Illustrator versions and production environments should be checked using your actual output.

## Installation

Download and extract the repository. Open a terminal **in the folder containing this README**, then run the commands for your operating system. This setup is only needed once.

### Windows — PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[scribus]"
```

### macOS / GNU/Linux

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ".[scribus]"
```

These commands install the converter and Scribus export dialogs. **For command-line PDF conversion only, replace `".[scribus]"` with `"."` in the second command.**

Keep the project folder together. Run the Scribus script from its original location so it can find the converter, dialogs, and palettes.

## Export AI from Scribus

1. Open the document you want to export in Scribus.
2. Choose **Script → Execute Script** and select [`integrations/scribus/export_ai.py`](integrations/scribus/export_ai.py).
3. Set **Pages**: `all` for every page, `current` for the current page, or a range such as `1,3-5`.
4. Select the **Export mode** and output filename, then click **Export**.
5. If preflight shows warnings, review them before proceeding. Export starts automatically when no confirmation is needed.

### Interface Language

The export dialogs follow **Scribus's interface language**:

- Japanese Scribus interface: Japanese export settings, progress, warnings, and completion messages.
- Any other Scribus interface language: English export settings, progress, warnings, and completion messages.

This uses the Scribus preference, not the operating system's language. The selected language is passed to the PDF progress window and conversion workers. Your document text, layer names, filenames, and spot color names are retained; generated default names follow the selected language.

### Separate Files or Multiple Artboards

| Export mode                             | Output                                                                                |
| --------------------------------------- | ------------------------------------------------------------------------------------- |
| Separate AI files per page — default    | One AI per page. Multipage exports use original page numbers, such as `design_001.ai` |
| Combine selected pages into one AI file | One `design.ai` containing an independent artboard for each selected page             |

Enable **Fail on unsupported features instead of rasterizing** when editable paths or spot separations are required. An unsupported page then stops the export instead of becoming an image.

The dialog also provides rasterization resolution, JSON reporting, time limits, document bleeds, and crop marks. Progress windows accept cancellation during PDF creation, preflight, and conversion. Scribus's synchronous PDF export must finish before a cancellation request takes effect.

AI files are published only after every selected page converts successfully. Conversion failure or cancellation keeps existing AI files. Ordinary publication failures trigger restoration from backups. Cancellation is disabled during publication and recovery. See the [Scribus export and recovery record](docs/scribus-export-safety.md) for implementation details and verification scope; that record is in Japanese.

## Convert PDF to AI from the Command Line

Run these commands from the project folder. Replace `input.pdf` and `output.ai` with your filenames. Quote paths containing spaces, for example `"My Design.pdf"`. Create the destination directory before conversion.

### Windows — PowerShell

```powershell
.\.venv\Scripts\python.exe run_pdf2ai.py input.pdf -o output.ai
```

### macOS / GNU/Linux

```sh
.venv/bin/python run_pdf2ai.py input.pdf -o output.ai
```

The basic command converts a single-page PDF. For multipage PDFs, select a page or an export mode:

| Purpose                          | Options                   | Result                                                              |
| -------------------------------- | ------------------------- | ------------------------------------------------------------------- |
| Convert page 2                   | `--page 2`                | Save to the specified `output.ai`                                   |
| Export every page separately     | `--pages all`             | Save `output_001.ai`, etc.                                          |
| Export selected pages separately | `--pages 1,3-5`           | Keep the original page numbers in filenames                         |
| Combine every page               | `--combine`               | Save one AI with multiple artboards                                 |
| Combine selected pages           | `--combine --pages 1,3-5` | Save the selected pages in one AI                                   |
| Reject raster fallback           | `--strict`                | Fail if unsupported features are found                              |
| Write a JSON report              | `--report result.json`    | Publish the AI files and report together                            |
| Allow overwriting                | `--overwrite`             | Replace existing AI files and the specified report                  |
| Display English                  | `--language en`           | English help, diagnostics, and generated defaults — the CLI default |
| Display Japanese                 | `--language ja`           | Japanese help, diagnostics, and generated defaults                  |

The options are the same on all operating systems. In the examples below, Windows users should replace `.venv/bin/python` with `.\.venv\Scripts\python.exe`.

Combine all pages into one AI:

```sh
.venv/bin/python run_pdf2ai.py input.pdf --combine -o output.ai
```

Check vector support without saving AI files:

```sh
.venv/bin/python run_pdf2ai.py input.pdf --check
```

Add `--combine` to the check command to inspect combined layout, color-space, and spot-definition constraints too. Preflight reports the first unsupported feature per page; it does not enumerate every possible issue or certify print quality.

Display Japanese help:

```sh
.venv/bin/python run_pdf2ai.py --language ja --help
```

### Additional CLI Options

| Option                         | Behavior                                                                                             |
| ------------------------------ | ---------------------------------------------------------------------------------------------------- |
| `--raster-dpi 300`             | Set raster fallback resolution; accepts 72–1200 dpi                                                  |
| `--timeout 60`                 | Limit each conversion to 60 seconds; `0` disables the limit. A timeout prevents publishing the batch |
| `--ask-password`               | Prompt for a PDF password without displaying it                                                      |
| `--password-file password.txt` | Read the password from the first line of a UTF-8 file                                                |
| `--flatten-annotations`        | Include annotation and form appearances as artwork; interactive behavior is not retained             |
| `--outline-text`               | Use Ghostscript for additional text outlining before conversion                                      |
| `--ghostscript PATH`           | Specify the Ghostscript executable                                                                   |
| `--output-dir DIRECTORY`       | Choose a destination directory instead of a single output filename                                   |

`--page` cannot be combined with `--pages` or `--combine`. Text preprocessing of layered PDFs is unsupported. For the full technical explanation in Japanese, see the [CLI and supported-feature guide](docs/technical.md).

## DIC and TOYO Spot Colors

Import the required palette in Scribus's color settings and use the colors **as spot colors**. DIC and TOYO have independent data and palette files. The two TOYO books have separate palettes.

| Palette                                                                          | Colors | Accepted name examples     | AI spot swatch                        |
| -------------------------------------------------------------------------------- | -----: | -------------------------- | ------------------------------------- |
| [DIC Lab](integrations/scribus/palettes/DIC_Lab.xml)                             |   1280 | `DIC 1`, `DIC 1s`, `DIC 4` | Legacy DIC book CMYK alternate values |
| [TOYO COLOR FINDER Lab](integrations/scribus/palettes/TOYO_COLOR_FINDER_Lab.xml) |   1079 | `CF 10001`, `CF10001`      | Matching Lab spot color               |
| [TOYO 94 Lab](integrations/scribus/palettes/TOYO_94_Lab.xml)                     |   1050 | `TOYO 0001`, `TOYO 1`      | Matching Lab spot color               |

The Scribus DIC palette uses Lab values, while recognized DIC names are normalized to the legacy CMYK definition for AI output. TOYO uses Lab; supported Lab inputs retain their actual values. The current and older TOYO books remain distinct.

On vector-converted pages, spot names and fill/stroke tints are preserved without converting spots to process colors. **Rasterized pages lose spot separations and editable paths.** Enable strict mode when these must be retained.

PDF2AI cannot restore spot names from artwork already converted to process colors. More details are available in the Japanese [DIC output specification](docs/dic-cmyk-reference.md) and [TOYO compatibility record](docs/toyo-spot-colors.md).

## Troubleshooting and Limitations

### Do I need Illustrator installed?

No. Normal conversion uses the included converter and color data.

### Can I edit text after conversion?

Text is converted to outlines and can be edited as shapes. It cannot be edited as text or have its font changed. Unsupported fonts or text features can cause raster fallback, or an error in strict mode.

### Why did my artwork become an image?

Review preflight or the JSON report for the unsupported feature. If editable vectors are required, adjust the source document or enable strict mode to stop the export. Rasterization affects the entire unsupported page.

### Scribus cannot find the conversion Python environment

Run the installation commands in the original project folder. The Scribus dialogs require the `".[scribus]"` installation. For another Python environment, set `PDF2AI_PYTHON` to its Python executable. Keep the project files together.

### Can I overwrite existing AI files?

Scribus asks for confirmation. In the CLI, specify `--overwrite` explicitly. Without permission, existing outputs are kept.

### Does AI output guarantee an identical print result?

No. Saving a valid AI file does not guarantee identical rendering for every PDF, Illustrator version, color setting, or print workflow. Check colors, shapes, outlined text, spot separations, and raster fallback before production.

## Japanese Documentation and Verification Records

See [interface language selection and verification](docs/interface-languages.md) for how English and Japanese are selected and tested.

- [日本語の導入・操作・特色ガイド](README_ja.md)
- [Technical guide: CLI, supported features, and file format](docs/technical.md)
- [Scribus export, cancellation, and recovery](docs/scribus-export-safety.md)
- [Illustrator format and rendering comparisons](docs/ai-files-format-alignment.md)
- [Pre-v1.0.0 verification: automated tests and distribution checks](docs/release-v1.0.0-check.md)
