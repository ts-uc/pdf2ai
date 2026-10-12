"""Configure Qt's standard controls in the external dialog process only."""
from pdf2ai.i18n import normalize_language


def configure_qt_language(app,language):
    from PySide6.QtCore import QLibraryInfo,QLocale,QTranslator
    selected=normalize_language(language)
    previous=getattr(app,'_pdf2ai_translator',None)
    if previous is not None:app.removeTranslator(previous)
    app._pdf2ai_translator=None
    QLocale.setDefault(QLocale('ja_JP' if selected=='ja' else 'en_US'))
    if selected=='ja':
        translator=QTranslator(app)
        if translator.load('qtbase_ja',QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(translator)
            app._pdf2ai_translator=translator
