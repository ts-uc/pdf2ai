import pikepdf
import pytest

from pdf2ai.cli import main, select_pages
from pdf2ai.native import convert
from pdf2ai.multiboard import convert_document
from pdf2ai.vector import ConversionError


def document(path,empty=False,password=None):
    pdf=pikepdf.new()
    if not empty:
        page=pdf.add_blank_page(page_size=(100,100))
        page.Contents=pdf.make_stream(b'10 10 20 20 re f')
    options={} if password is None else {'encryption':pikepdf.Encryption(owner='owner',user=password,R=6)}
    pdf.save(path,**options)


@pytest.mark.parametrize('mode',[[],['--pages','all'],['--combine'],['--check']])
def test_password_pdf_cli_returns_diagnostic_without_traceback(tmp_path,capsys,mode):
    source=tmp_path/'locked.pdf';document(source,password='secret')
    assert main([str(source),*mode])==1
    assert 'ERROR' in capsys.readouterr().err
    assert not list(tmp_path.glob('*.ai'))


@pytest.mark.parametrize('mode',[['--pages','all'],['--combine'],['--check']])
def test_empty_pdf_cannot_be_reported_as_success(tmp_path,mode):
    source=tmp_path/'empty.pdf';document(source,empty=True)
    assert main([str(source),*mode])==1
    assert not list(tmp_path.glob('*.ai'))


def test_page_output_cannot_silently_replace_requested_extension(tmp_path):
    source=tmp_path/'input.pdf';document(source)
    assert main([str(source),'--pages','1','-o',str(tmp_path/'out.pdf')])==1
    assert not (tmp_path/'out_001.ai').exists()


@pytest.mark.parametrize('mode',[[],['--check'],['--combine']])
def test_explicit_empty_selection_is_rejected(tmp_path,mode):
    source=tmp_path/'input.pdf';document(source)
    assert main([str(source),'--pages','',*mode])==1
    assert not list(tmp_path.glob('*.ai'))


@pytest.mark.parametrize('number',[0,-1,True,1.5,'1'])
def test_single_page_api_rejects_invalid_page_without_overwriting(tmp_path,number):
    source=tmp_path/'input.pdf';output=tmp_path/'previous.ai'
    document(source);output.write_bytes(b'previous')
    with pytest.raises(ConversionError,match='positive integer'):
        convert(source,output,page_number=number,overwrite=True)
    assert output.read_bytes()==b'previous'


@pytest.mark.parametrize('combined',[False,True])
def test_output_directory_is_rejected_without_processing_pdf(tmp_path,monkeypatch,combined):
    source=tmp_path/'input.pdf';output=tmp_path/'out.ai'
    document(source);output.mkdir()
    def forbidden(*args,**kwargs):raise AssertionError('Should not open PDF')
    monkeypatch.setattr(pikepdf,'open',forbidden)
    with pytest.raises(ConversionError,match='directory'):
        (convert_document if combined else convert)(source,output,overwrite=True)


def test_cli_report_directory_is_rejected_before_first_ai(tmp_path):
    source=tmp_path/'input.pdf';report=tmp_path/'report.json'
    document(source);report.mkdir()
    assert main([str(source),'--report',str(report)])==1
    assert not source.with_suffix('.ai').exists()


def test_page_selector_normalizes_whitespace_and_rejects_zero_pages():
    assert select_pages(' all ',1)==[1]
    with pytest.raises(ConversionError,match='ページがありません'):
        select_pages('all',0)
