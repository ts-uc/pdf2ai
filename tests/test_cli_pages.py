import json
import pikepdf
import pytest

from pdf2ai.cli import main, select_pages, publish_report
from pdf2ai.vector import ConversionError
from pdf2ai.multiboard import convert_document


def source_pdf(path):
    pdf = pikepdf.new()
    for width in (100, 200, 300):
        page = pdf.add_blank_page(page_size=(width, 100))
        page.Contents = pdf.make_stream(b'0 0 10 10 re f')
    pdf.save(path)


@pytest.mark.parametrize('selection', ['0', '4', '3-1', '1,1', '1,', '1-999999999'])
def test_invalid_selection(selection):
    with pytest.raises(ConversionError):
        select_pages(selection, 3)


def test_selected_combination_keeps_pdf_order_and_reports(tmp_path):
    source = tmp_path/'source.pdf'
    source_pdf(source)
    output = tmp_path/'out.ai'
    reports = convert_document(source, output, pages=[3, 1])
    assert [r['page'] for r in reports] == [3, 1]
    with pikepdf.open(output) as pdf:
        assert [float(p.MediaBox[2]) for p in pdf.pages] == [300, 100]


def test_cli_page_files_and_combination(tmp_path):
    source = tmp_path/'source.pdf'
    source_pdf(source)
    assert main([str(source), '--pages', '1,3', '-o', str(tmp_path/'page.ai')]) == 0
    assert (tmp_path/'page_001.ai').exists() and (tmp_path/'page_003.ai').exists()
    report = tmp_path/'report.json'
    assert main([str(source), '--combine', '--pages', '3,1', '-o', str(tmp_path/'combined.ai'), '--report', str(report)]) == 0
    assert [r['page'] for r in json.loads(report.read_text())] == [3, 1]


def test_report_conflict_is_rejected_before_conversion(tmp_path):
    source = tmp_path/'source.pdf'
    source_pdf(source)
    original = source.read_bytes()
    assert main([str(source), '--report', str(source)]) == 1
    assert source.read_bytes() == original
    assert not source.with_suffix('.ai').exists()


def test_report_publish_failure_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path/'report.json'
    path.write_text('previous')
    def fail(*args):
        raise OSError('disk failure')
    monkeypatch.setattr('pdf2ai.cli.os.replace', fail)
    with pytest.raises(OSError):
        publish_report(path, [{'ok': True}], overwrite=True)
    assert path.read_text() == 'previous'
    assert not list(tmp_path.glob('.pdf2ai-report-*'))


@pytest.mark.parametrize('check', [False, True])
@pytest.mark.parametrize('overwrite', [False, True])
def test_cli_existing_report_requires_overwrite(tmp_path, check, overwrite):
    source = tmp_path/'source.pdf'
    source_pdf(source)
    report = tmp_path/'report.json'
    report.write_text('previous')
    args = [str(source), '--page', '1', '--report', str(report)]
    if check:
        args.append('--check')
    if overwrite:
        args.append('--overwrite')
    assert main(args) == (0 if overwrite else 1)
    if overwrite:
        assert json.loads(report.read_text())[0]['page'] == 1
        assert source.with_suffix('.ai').exists() == (not check)
    else:
        assert report.read_text() == 'previous'
        assert not source.with_suffix('.ai').exists()


def test_report_created_during_publication_is_preserved(tmp_path, monkeypatch):
    path = tmp_path/'report.json'
    import os
    real_link = os.link

    def race(source, destination):
        path.write_text('other writer')
        return real_link(source, destination)

    monkeypatch.setattr('pdf2ai.cli.os.link', race)
    with pytest.raises(FileExistsError):
        publish_report(path, [{'ok': True}])
    assert path.read_text() == 'other writer'
    assert not list(tmp_path.glob('.pdf2ai-report-*'))


@pytest.mark.parametrize('check', [False, True])
def test_cli_dangling_report_symlink_is_rejected_before_conversion(tmp_path, check):
    source = tmp_path/'source.pdf'
    source_pdf(source)
    report = tmp_path/'report.json'
    report.symlink_to(tmp_path/'missing.json')
    args = [str(source), '--page', '1', '--report', str(report)]
    if check:
        args.append('--check')
    assert main(args) == 1
    assert report.is_symlink()
    assert not source.with_suffix('.ai').exists()


def test_selected_fallback_uses_original_page_index(tmp_path):
    source = tmp_path/'source.pdf'
    source_pdf(source)
    with pikepdf.open(source, allow_overwriting_input=True) as pdf:
        pdf.pages[2].Contents = pdf.make_stream(b'0 w 0 0 m 100 100 l S')
        pdf.save(source)
    reports = convert_document(source, tmp_path/'out.ai', pages=[3], raster_dpi=72)
    assert reports[0]['rasterized'] and reports[0]['page'] == 3
    assert reports[0]['page_box'][2] == 300


def test_check_inspects_every_page_without_publishing_ai(tmp_path, capsys):
    source = tmp_path/'source.pdf'
    source_pdf(source)
    with pikepdf.open(source, allow_overwriting_input=True) as pdf:
        pdf.pages[1].Contents = pdf.make_stream(b'0 w 0 0 m 100 100 l S')
        pdf.save(source)
    report = tmp_path/'report.json'
    assert main([str(source), '--check', '--report', str(report)]) == 1
    results = json.loads(report.read_text())
    assert [r['native_supported'] for r in results] == [True, False, True]
    assert all(r['inspection_only'] for r in results)
    assert 'Hairline' in results[1]['first_blocker'] or 'hairline' in results[1]['first_blocker']
    assert not list(tmp_path.glob('*.ai'))
