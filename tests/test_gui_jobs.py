import json
import threading

import pikepdf
import pytest

from pdf2ai.gui_jobs import plan_jobs, run_jobs
from pdf2ai.vector import ConversionError


def source_pdf(path,unsupported=False):
    pdf=pikepdf.new()
    for number in range(3):
        page=pdf.add_blank_page(page_size=(100,100))
        page.Contents=pdf.make_stream(b'0 w 10 10 m 50 50 l S' if unsupported and number==1
                                      else b'1 0 0 rg 10 10 20 20 re f')
    pdf.save(path)


def run(plans,**options):
    events=[]
    run_jobs(plans,combined=False,overwrite=False,strict=True,outline=False,resolution=300,
             cancelled=lambda:False,emit=events.append,**options)
    return events


def test_page_failure_has_context_continues_and_counts_only_saved_pages(tmp_path):
    source=tmp_path/'source.pdf';source_pdf(source,True)
    plans=plan_jobs([source],tmp_path,'all',False)
    events=run(plans,report_path=tmp_path/'report.json')
    summary=events[-1][1]
    assert events[-1][0]=='done'
    assert (summary['saved'],summary['failed'],summary['unprocessed'])==(2,1,0)
    assert (tmp_path/'source_001.ai').exists() and (tmp_path/'source_003.ai').exists()
    assert not (tmp_path/'source_002.ai').exists()
    report=json.loads((tmp_path/'report.json').read_text())
    assert report[1]['pages']==[2] and 'error' in report[1]
    assert any('source.pdf（ページ 2）' in event[1] for event in events if event[0]=='log')
    assert [e[1] for e in events if e[0]=='progress']==[0,1,1,2,2,3]


def test_cancel_during_combined_analysis_does_not_report_pages_as_saved(tmp_path):
    source=tmp_path/'source.pdf';source_pdf(source)
    output=tmp_path/'source.ai';output.write_bytes(b'previous')
    events=[];stop=threading.Event()
    def emit(event):
        events.append(event)
        if event[0]=='progress' and event[1]==1:stop.set()
    log=tmp_path/'report.json'
    run_jobs(plan_jobs([source],tmp_path,'all',True),combined=True,overwrite=True,strict=True,
             outline=False,resolution=300,cancelled=stop.is_set,emit=emit,report_path=log)
    summary=events[-1][1]
    assert summary['cancelled'] and summary['saved']==0 and summary['unprocessed']==3
    assert output.read_bytes()==b'previous'
    assert json.loads(log.read_text())[-1]['cancelled']


def test_report_failure_does_not_hide_successful_ai_and_always_finishes(tmp_path,monkeypatch):
    source=tmp_path/'source.pdf';source_pdf(source)
    def fail(*args):raise OSError('disk full')
    monkeypatch.setattr('pdf2ai.gui_jobs.publish_report',fail)
    events=run(plan_jobs([source],tmp_path,'1',False),report_path=tmp_path/'report.json')
    assert events[-1][0]=='done'
    assert events[-1][1]['saved']==1 and events[-1][1]['report_error']=='disk full'
    assert (tmp_path/'source_001.ai').exists()


def test_empty_page_selection_keeps_legacy_single_page_name(tmp_path):
    source=tmp_path/'one.pdf';pdf=pikepdf.new();pdf.add_blank_page();pdf.save(source)
    assert plan_jobs([source],tmp_path,'',False)[0][1].name=='one.ai'
    assert plan_jobs([source],tmp_path,'1',False)[0][1].name=='one_001.ai'


def test_invalid_page_message_identifies_the_input(tmp_path):
    source=tmp_path/'source.pdf';source_pdf(source)
    with pytest.raises(ConversionError,match='source.pdf.*all'):
        plan_jobs([source],tmp_path,'',False)


def test_output_collision_is_detected_before_processing(tmp_path):
    first=tmp_path/'first';second=tmp_path/'second';first.mkdir();second.mkdir()
    source_pdf(first/'source.pdf');source_pdf(second/'source.pdf')
    with pytest.raises(ConversionError,match='保存先を分けて'):
        plan_jobs([first/'source.pdf',second/'source.pdf'],tmp_path,'all',False)
    assert not list(tmp_path.glob('*.ai'))


@pytest.mark.parametrize('password',['','secret'])
def test_encrypted_pdf_is_diagnosed_during_planning(tmp_path,password):
    source=tmp_path/'encrypted.pdf'
    pdf=pikepdf.new();pdf.add_blank_page()
    pdf.save(source,encryption=pikepdf.Encryption(owner='owner',user=password,R=6))
    with pytest.raises(ConversionError,match='encrypted.pdf.*暗号化されていないPDF'):
        plan_jobs([source],tmp_path,'all',False)
    assert not list(tmp_path.glob('*.ai'))
