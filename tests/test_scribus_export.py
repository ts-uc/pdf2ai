"""Scribus bridge: page mapping, external worker, export settings and conflicts."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pikepdf
import pytest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'integrations'/'scribus'/'export_ai.py'
spec=importlib.util.spec_from_file_location('scribus_export',SCRIPT)
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)


@pytest.mark.parametrize('value,expected',[('all',[1,2,3,4]),('current',[3]),('1,3-4',[1,3,4]),('4,1,1',[1,4])])
def test_page_selection(value,expected):
    assert bridge.parse_pages(value,4,3)==expected


@pytest.mark.parametrize('value',['0','5','4-2','1-99','1,','x'])
def test_invalid_page_selection(value):
    with pytest.raises(ValueError):bridge.parse_pages(value,4,3)


def test_pdf_options_preserve_layers_spots_and_outline_text(tmp_path):
    pdf=SimpleNamespace()
    def save():Path(pdf.file).write_bytes(b'pdf')
    pdf.save=save
    bridge.export_pdf(SimpleNamespace(PDFfile=lambda:pdf),tmp_path/'test.pdf',[2,4])
    assert pdf.pages==[2,4] and pdf.useLayers and pdf.usespot
    assert pdf.version==15 and pdf.fontEmbedding==1 and not pdf.domulti
    assert not pdf.encrypt and not pdf.profiles and not pdf.profilei
    assert pdf.downsample==0 and pdf.embedPDF and not pdf.cropMarks


def selected_pdf(path):
    with pikepdf.open(ROOT/'sample'/'conversion_pages.pdf') as pdf:
        del pdf.pages[2];del pdf.pages[0];pdf.save(path)


def test_external_worker_page_mapping_and_report(tmp_path):
    source=tmp_path/'input.pdf';selected_pdf(source)
    base=tmp_path/'日本語 空白.ai'
    request={'pdf':str(source),'pages':[2,4],'output':str(base),'document':'layout.sla','write_report':True}
    config=tmp_path/'request.json';config.write_text(json.dumps(request),encoding='utf-8')
    result=subprocess.run([sys.executable,str(SCRIPT),'--worker',str(config)],capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==0,result.stderr
    report=json.loads(base.with_suffix('.report.json').read_text(encoding='utf-8'))
    assert [r['page'] for r in report['results']]==[2,4]
    assert [r['output'] for r in report['results']]==['日本語 空白_002.ai','日本語 空白_004.ai']
    for r in report['results']:
        assert not r['rasterized'] and r['input']=='layout.sla'
        with pikepdf.open(tmp_path/r['output']) as pdf:
            assert len(pdf.pages)==1 and pdf.pages[0].obj.PieceInfo.Illustrator.Private.CreatorVersion==24
    previous=[(tmp_path/r['output']).read_bytes() for r in report['results']]
    assert subprocess.run([sys.executable,str(SCRIPT),'--worker',str(config)],capture_output=True).returncode==2
    assert previous==[(tmp_path/r['output']).read_bytes() for r in report['results']]


def test_fallback_and_strict_failure_report(tmp_path):
    source=tmp_path/'input.pdf'
    with pikepdf.open(ROOT/'sample'/'conversion_fallback.pdf') as pdf:
        while len(pdf.pages)>1:del pdf.pages[-1]
        pdf.save(source)
    request={'pdf':str(source),'pages':[7],'output':str(tmp_path/'auto.ai'),'dpi':72}
    result=bridge.convert_export(request)['results'][0]
    assert result['rasterized'] and result['page']==7 and result['lost_features']
    request.update(output=str(tmp_path/'strict.ai'),strict=True,write_report=True)
    result=bridge.convert_export(request)['results'][0]
    assert 'error' in result and not (tmp_path/'strict.ai').exists()
    assert (tmp_path/'strict.report.json').exists()


def test_batch_conflict_checked_before_first_output(tmp_path):
    source=tmp_path/'input.pdf';selected_pdf(source)
    (tmp_path/'export_004.ai').write_bytes(b'keep')
    with pytest.raises(FileExistsError):bridge.convert_export({'pdf':str(source),'pages':[2,4],'output':str(tmp_path/'export.ai')})
    assert not (tmp_path/'export_002.ai').exists()
    assert (tmp_path/'export_004.ai').read_bytes()==b'keep'


def test_page_count_mismatch_does_not_write(tmp_path):
    source=tmp_path/'input.pdf';selected_pdf(source)
    with pytest.raises(ValueError,match='ページ数'):
        bridge.convert_export({'pdf':str(source),'pages':[1],'output':str(tmp_path/'a.ai')})
    assert not (tmp_path/'a.ai').exists()


def test_child_environment_removes_embedded_python_settings(monkeypatch):
    monkeypatch.setenv('PYTHONHOME','scribus-python');monkeypatch.setenv('PYTHONPATH','scribus-modules')
    environment=bridge.child_environment()
    assert 'PYTHONHOME' not in environment and 'PYTHONPATH' not in environment
    assert environment['PYTHONIOENCODING']=='utf-8'


def test_outlined_glyph_form_with_reversed_bbox(tmp_path):
    from pdf2ai.native import convert
    from pdf2ai.vector import read_drawing
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    form=pdf.make_stream(b'0 0 0 1 k 10 -70 60 50 re f')
    form.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Form,BBox=[80,-10,0,-80],Resources=pikepdf.Dictionary()))
    page.obj.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Glyph=form))
    page.obj.Contents=pdf.make_stream(b'q 1 0 0 1 0 90 cm /Glyph Do Q')
    source=tmp_path/'glyph.pdf';pdf.save(source)
    result=convert(source,tmp_path/'glyph.ai',raster_fallback=False)
    assert not result['rasterized'] and result['painted_paths']==1
    with pikepdf.open(source) as pdf:
        drawing=read_drawing(pdf.pages[0]);commands=drawing.paths[0].state.clips[0].paths[0].commands
        assert commands[0][1]==(0,10) and commands[2][1]==(80,80)


def test_worker_default_has_no_log_and_keeps_existing_log(tmp_path):
    source=tmp_path/'input.pdf'
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Contents=pdf.make_stream(b'10 10 30 30 re f');pdf.save(source)
    base=tmp_path/'result.ai';log=base.with_suffix('.report.json')
    log.write_bytes(b'previous log')
    config=tmp_path/'request.json'
    config.write_text(json.dumps({'pdf':str(source),'pages':[1],'output':str(base)}))
    result=subprocess.run([sys.executable,str(SCRIPT),'--worker',str(config)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    summary=json.loads(result.stdout)
    assert len(summary['results'])==1 and not summary['results'][0]['rasterized']
    assert base.exists() and log.read_bytes()==b'previous log'
    base.unlink();log.unlink()
    result=subprocess.run([sys.executable,str(SCRIPT),'--worker',str(config)],capture_output=True,text=True)
    assert result.returncode==0 and base.exists() and not log.exists()


def test_optional_log_conflict_checked_before_conversion(tmp_path):
    source=tmp_path/'input.pdf';selected_pdf(source)
    log=tmp_path/'result.report.json';log.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        bridge.convert_export({'pdf':str(source),'pages':[2,4],'output':str(tmp_path/'result.ai'),'write_report':True})
    assert not (tmp_path/'result_002.ai').exists() and log.read_bytes()==b'keep'


def test_default_output_uses_original_document_directory(tmp_path,monkeypatch):
    directory=tmp_path/'日本語 空白';directory.mkdir()
    assert bridge.default_output(str(directory/'文書.sla'))==directory/'文書.ai'
    assert bridge.default_output(str(directory/'文書.sla.gz'))==directory/'文書.ai'
    monkeypatch.chdir(tmp_path)
    assert bridge.default_output('')==tmp_path/'document.ai'


@pytest.mark.parametrize('checked',[False,True])
def test_checkbox_dialog_and_save_directory(tmp_path,checked):
    pytest.importorskip('PySide6.QtWidgets')
    code=r'''
import importlib.util,json,sys
from pathlib import Path
from PySide6.QtWidgets import QApplication,QCheckBox,QLineEdit,QPushButton,QDialogButtonBox,QFileDialog
spec=importlib.util.spec_from_file_location('bridge',sys.argv[1])
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
app=QApplication(['test'])
document=Path(sys.argv[2])/'original.sla'
dialog=bridge.build_export_dialog(str(document),4,2)
checkbox=dialog.findChild(QCheckBox,'write_report')
assert not checkbox.isChecked()
expected=str(document.with_suffix('.ai'))
assert dialog.findChild(QLineEdit,'output').text()==expected
calls=[]
def choose(parent,caption,initial,filter,**kwargs):
    calls.append(initial)
    return (expected,'')
QFileDialog.getSaveFileName=choose
next(b for b in dialog.findChildren(QPushButton) if b.text()=='参照…').click()
assert calls==[expected]
dialog.findChild(QLineEdit,'pages').setText('current')
checkbox.setChecked(sys.argv[3]=='True')
dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
print(json.dumps(dialog.export_options))
'''
    env=bridge.child_environment();env['QT_QPA_PLATFORM']='offscreen'
    result=subprocess.run([sys.executable,'-c',code,str(SCRIPT),str(tmp_path),str(checked)],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'pages':[2],'output':str(tmp_path/'original.ai'),'write_report':checked}
