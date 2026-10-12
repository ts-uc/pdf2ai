# English and Japanese Interface Support

The Scribus bridge selects its language from `scribus.getGuiLanguage()`. Japanese locale codes (`ja`, `ja_JP`, `ja-JP`) select Japanese; every other locale, including an unavailable or empty setting, selects English. The operating system locale does not select the plugin language.

The selected language travels with export settings and worker requests. It applies to export settings, the file chooser, PDF creation progress, preflight, conversion progress, cancellation, timeouts, overwrite prompts, errors, and completion messages. Qt's standard controls are configured in the external dialog process; the Scribus application's locale is not changed. File selection uses a Qt dialog so an OS-native chooser cannot override the selected interface language.

The CLI defaults to English. Use `--language ja` for Japanese, or `--language en` for English. The language is also passed to isolated timeout workers. JSON field names remain stable. Input filenames, document text, layer names, and spot color names are preserved; generated default names are localized.

Direct Python conversion APIs retain their previous Japanese defaults. A caller can use `pdf2ai.i18n.use_language('en')` around a conversion to select English without changing other calls. Dialog callbacks keep the language selected when the dialog was created.

## Documentation

[README.md](../README.md) is the primary English guide. It links to the detailed [Japanese guide](../README_ja.md) near the beginning. Historical technical and verification records remain in Japanese and are identified as such in the English guide.

## Verification — 2026-10-12

- All 560 automated tests passed, with five existing SWIG deprecation warnings.
- Locale selection, translation placeholders, English/Japanese CLI help, worker propagation, and dialog callbacks were tested.
- Actual Qt sessions were tested in both languages for successful publication, cancellation, timeout, strict-mode rejection, and cancellation requested during publication. Existing output protection remains intact.
- Scribus was launched with isolated preferences and no user document. Its actual API returned `ja` and `en`; the plugin selected Japanese and English respectively.
- English/Japanese sample conversions retained identical PDF drawing instructions, spot definitions, and rendered appearance.
- Japanese DIC and edmondson editing streams matched the existing reference exports, excluding source title, creation date, and generated UUIDs.
- Reference AI files, DIC/TOYO JSON data, and XML palettes retained their SHA-256 hashes.
- A wheel containing the translation module was built. English/Japanese CLI help and strict four-artboard conversion succeeded from the wheel.
- README links and command options were checked. English export dialog layout was visually inspected.

Disposable verification files are in `output/i18n-scribus-check/` and `output/i18n-check-dist/`. The reference files in `ai_files` were not modified.
