"""Locale selection must follow Scribus, survive workers, and preserve artwork."""
import json
import os
from pathlib import Path
import re
import string
import subprocess
import sys
from types import SimpleNamespace

import pikepdf
import pytest

from pdf2ai.cli import main
from pdf2ai.i18n import MESSAGES,get_language,normalize_language,tr,use_language
from pdf2ai.native import convert,read_private
from test_scribus_export import bridge,SCRIPT


@pytest.mark.parametrize('locale,expected',[
    ('ja','ja'),('ja_JP','ja'),('ja-JP','ja'),('JA_jp','ja'),
    ('en_GB','en'),('de','en'),('fr_FR','en'),('zh_CN','en'),('', 'en'),(None,'en'),
])
def test_scribus_language_uses_host_preference(locale,expected):
    assert bridge.scribus_language(SimpleNamespace(getGuiLanguage=lambda:locale))==expected
    assert normalize_language(locale)==expected


def test_missing_host_language_falls_back_to_english():
    assert bridge.scribus_language(SimpleNamespace())=='en'


def test_translation_placeholders_are_preserved():
    def fields(text):return [field for _,field,_,_ in string.Formatter().parse(text) if field is not None]
    for japanese,english in MESSAGES.items():
        assert fields(japanese)==fields(english),(japanese,english)
        assert not re.search(r'[ぁ-んァ-ヶ一-龠]',english)


@pytest.mark.parametrize('language,heading',[('en','Convert PDF paths'),('ja','PDFのパス')])
def test_cli_help_language_is_explicit_and_does_not_leak(language,heading,capsys):
    before=get_language()
    with pytest.raises(SystemExit) as error:main(['--language',language,'--help'])
    assert error.value.code==0 and heading in capsys.readouterr().out
    assert get_language()==before


def test_cli_defaults_to_english(capsys):
    with pytest.raises(SystemExit):main(['--help'])
    assert 'Input PDF files' in capsys.readouterr().out


@pytest.mark.parametrize('locale,title',[('ja_JP','AI書き出し'),('de_DE','AI Export')])
def test_no_document_message_uses_scribus_language_and_restores_context(locale,title):
    messages=[];before=get_language()
    host=SimpleNamespace(getGuiLanguage=lambda:locale,haveDoc=lambda:False,ICON_WARNING=1,
                         messageBox=lambda *args:messages.append(args))
    bridge.scribus_main(host)
    assert messages[0][0]==title
    assert get_language()==before


@pytest.mark.parametrize('language',['en','ja'])
def test_qt_dialogs_and_callbacks_keep_language(language,tmp_path):
    pytest.importorskip('PySide6.QtWidgets')
    code=r'''
import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import export_ai as bridge
from progress_dialog import build_preflight_dialog,ExportSession
from pdf_progress import PdfProgress
from pdf2ai.i18n import use_language
from PySide6.QtWidgets import QApplication,QDialogButtonBox,QPushButton,QPlainTextEdit,QLineEdit,QMessageBox
app=QApplication(['test']);language=sys.argv[3];base=Path(sys.argv[2])
dialog=bridge.build_export_dialog(str(base/'document.sla'),2,1,language)
expected='AI Export' if language=='en' else 'AI書き出し'
assert dialog.windowTitle()==expected
buttons=dialog.findChild(QDialogButtonBox)
assert buttons.button(QDialogButtonBox.StandardButton.Cancel).text()==('Cancel' if language=='en' else 'キャンセル')
# The callback must not use a subsequently selected language.
messages=[];QMessageBox.warning=lambda parent,title,message:messages.append((title,message))
with use_language('ja' if language=='en' else 'en'):
 dialog.findChild(QLineEdit,'pages').setText('0')
 buttons.button(QDialogButtonBox.StandardButton.Ok).click()
assert messages[0][0]==expected
assert ('Page numbers' in messages[0][1])==(language=='en')
dialog.findChild(QLineEdit,'pages').setText('all')
buttons.button(QDialogButtonBox.StandardButton.Ok).click()
assert dialog.export_options['language']==language
summary={'language':language,'can_export':False,'combined_constraints_checked':True,
         'results':[{'page':2,'native_supported':False,'first_blocker':'Unsupported mask','combined_blocker':'Cannot combine'}]}
preflight=build_preflight_dialog(summary)
assert preflight.windowTitle().startswith(expected)
assert ('Page 2:' in preflight.findChild(QPlainTextEdit).toPlainText())==(language=='en')
request={'language':language,'pages':[1,2],'cancel':str(base/'cancel'),
         'done':str(base/'done'),'output':str(base/'output.ai')}
pdf=PdfProgress(request)
assert pdf.windowTitle().startswith(expected)
with use_language('ja' if language=='en' else 'en'):pdf.cancel(True)
assert ('Time limit exceeded' in pdf.label.text())==(language=='en')
config=base/'request.json';config.write_text(json.dumps(request))
session=ExportSession(config,Path(sys.argv[1])/'export_ai.py')
with use_language('ja' if language=='en' else 'en'):session.cancel()
assert ('Stopping conversion' in session.label.text())==(language=='en')
assert json.loads(config.read_text())['language']==language
print('PASS')
'''
    env=bridge.child_environment();env['QT_QPA_PLATFORM']='offscreen'
    result=subprocess.run([sys.executable,'-c',code,str(SCRIPT.parent),str(tmp_path),language],
                          env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert 'PASS' in result.stdout


@pytest.mark.parametrize('language',['en','ja'])
def test_cli_timeout_worker_receives_language(tmp_path,language):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Contents=pdf.make_stream(b'0 0 0 1 k 10 10 30 30 re f')
    source=tmp_path/'source.pdf';pdf.save(source)
    output=tmp_path/'output.ai'
    assert main([str(source),'-o',str(output),'--timeout','30','--language',language])==0
    with pikepdf.open(output) as ai:
        private=read_private(ai)
        assert ('Layer 1' if language=='en' else 'レイヤー 1').encode() in private
        assert ('Artboard 1' if language=='en' else 'アートボード 1').encode() in private


def test_bilingual_output_keeps_pdf_artwork_and_spot_values(tmp_path):
    from PIL import ImageChops
    import importlib.util
    spec=importlib.util.spec_from_file_location("i18n_fidelity",Path("tools/compare_fidelity.py"))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    render=module.render
    source=Path('sample/conversion_native.pdf')
    outputs=[]
    for language in ('ja','en'):
        output=tmp_path/(language+'.ai')
        with use_language(language):report=convert(source,output,raster_fallback=False)
        outputs.append(output)
        assert not report['rasterized']
    with pikepdf.open(outputs[0]) as ja,pikepdf.open(outputs[1]) as en:
        assert len(ja.pages)==len(en.pages)==1
        assert pikepdf.unparse_content_stream(pikepdf.parse_content_stream(ja.pages[0]))==pikepdf.unparse_content_stream(pikepdf.parse_content_stream(en.pages[0]))
        from pdf2ai.vector import read_drawing
        assert read_drawing(ja.pages[0],root=ja.Root).spots==read_drawing(en.pages[0],root=en.Root).spots
    assert ImageChops.difference(render(outputs[0]),render(outputs[1])).getbbox() is None


def test_qt_standard_controls_can_switch_back_to_english():
    pytest.importorskip('PySide6.QtWidgets')
    code=r'''
import sys
sys.path.insert(0,sys.argv[1])
from qt_language import configure_qt_language
from PySide6.QtWidgets import QApplication,QDialogButtonBox
app=QApplication(['test'])
configure_qt_language(app,'ja')
assert app._pdf2ai_translator is not None
configure_qt_language(app,'fr_FR')
assert app._pdf2ai_translator is None
button=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
assert button.button(QDialogButtonBox.StandardButton.Cancel).text()=='Cancel'
'''
    env=bridge.child_environment();env['QT_QPA_PLATFORM']='offscreen'
    result=subprocess.run([sys.executable,'-c',code,str(SCRIPT.parent)],env=env,
                          capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
