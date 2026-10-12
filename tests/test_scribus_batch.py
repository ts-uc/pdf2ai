import json
import os
from pathlib import Path
import subprocess
import sys

import pikepdf
import pytest

from pdf2ai.batch_publish import publish_batch
from test_scribus_export import bridge, SCRIPT


def source_pdf(path,unsupported=False):
    pdf=pikepdf.new()
    for index in range(2):
        page=pdf.add_blank_page(page_size=(100,100))
        page.Contents=pdf.make_stream(b'0 w 10 10 m 50 50 l S' if index==1 and unsupported
                                     else b'1 0 0 rg 10 10 20 20 re f')
    pdf.save(path)


@pytest.mark.parametrize('overwrite',[False,True])
def test_mid_publication_failure_restores_all_previous_files(tmp_path,monkeypatch,overwrite):
    stage=tmp_path/'staging';stage.mkdir()
    sources=[stage/'a',stage/'b'];destinations=[tmp_path/'a.ai',tmp_path/'b.ai']
    for source in sources:source.write_bytes(b'new')
    if overwrite:
        for dest in destinations:dest.write_bytes(b'old')
    real_replace=os.replace;real_link=os.link
    def fail(source,destination,*args,**kwargs):
        if Path(source)==sources[1] and Path(destination)==destinations[1]:raise OSError('publication failed')
        return (real_replace if overwrite else real_link)(source,destination,*args,**kwargs)
    monkeypatch.setattr('pdf2ai.batch_publish.os.'+('replace' if overwrite else 'link'),fail)
    with pytest.raises(OSError,match='publication failed'):
        publish_batch(zip(sources,destinations),overwrite=overwrite)
    assert all(p.read_bytes()==b'old' for p in destinations) if overwrite else not any(p.exists() for p in destinations)
    assert not list(tmp_path.glob('.pdf2ai-recovery-*'))


def test_late_output_conflict_keeps_other_writer_file_and_removes_earlier_output(tmp_path,monkeypatch):
    stage=tmp_path/'staging';stage.mkdir()
    first=stage/'first';second=stage/'second'
    first.write_bytes(b'new');second.write_bytes(b'new')
    a=tmp_path/'a.ai';b=tmp_path/'b.ai';real=os.link
    def race(source,destination):
        if Path(destination)==b:b.write_bytes(b'other writer')
        return real(source,destination)
    monkeypatch.setattr('pdf2ai.batch_publish.os.link',race)
    with pytest.raises(FileExistsError):publish_batch([(first,a),(second,b)])
    assert not a.exists() and b.read_bytes()==b'other writer'


def test_failed_restore_retains_backup_and_manifest(tmp_path,monkeypatch):
    stage=tmp_path/'staging';stage.mkdir()
    first=stage/'first';second=stage/'second';a=tmp_path/'a.ai';b=tmp_path/'b.ai'
    first.write_bytes(b'new');second.write_bytes(b'new');a.write_bytes(b'old a');b.write_bytes(b'old b')
    real=os.replace
    def fail(source,destination):
        if Path(destination)==b or Path(source).parent.name.startswith('.pdf2ai-recovery-'):
            raise OSError('disk failure')
        return real(source,destination)
    monkeypatch.setattr('pdf2ai.batch_publish.os.replace',fail)
    with pytest.raises(RuntimeError,match='バックアップ'):
        publish_batch([(first,a),(second,b)],overwrite=True)
    recovery=list(tmp_path.glob('.pdf2ai-recovery-*'))
    assert len(recovery)==1 and (recovery[0]/'0').read_bytes()==b'old a'
    assert (recovery[0]/'manifest.json').exists() and b.read_bytes()==b'old b'


def test_keyboard_interrupt_during_publication_restores_previous_files(tmp_path,monkeypatch):
    stage=tmp_path/'staging';stage.mkdir()
    first=stage/'first';second=stage/'second';a=tmp_path/'a.ai';b=tmp_path/'b.ai'
    first.write_bytes(b'new');second.write_bytes(b'new');a.write_bytes(b'old a');b.write_bytes(b'old b')
    real=os.replace
    def interrupt(source,destination):
        if Path(source)==second:raise KeyboardInterrupt()
        return real(source,destination)
    monkeypatch.setattr('pdf2ai.batch_publish.os.replace',interrupt)
    with pytest.raises(KeyboardInterrupt):publish_batch([(first,a),(second,b)],overwrite=True)
    assert a.read_bytes()==b'old a' and b.read_bytes()==b'old b'


@pytest.mark.parametrize('overwrite',[False,True])
def test_separate_strict_failure_publishes_no_ai_but_returns_diagnostics(tmp_path,overwrite):
    source=tmp_path/'input.pdf';source_pdf(source,True)
    first=tmp_path/'export_003.ai';second=tmp_path/'export_007.ai'
    if overwrite:first.write_bytes(b'old first');second.write_bytes(b'old second')
    summary=bridge.convert_export({'pdf':str(source),'pages':[3,7],'output':str(tmp_path/'export.ai'),
                                   'overwrite':overwrite,'write_report':True,'strict':True})
    assert not summary['committed'] and all(not r['published'] for r in summary['results'])
    assert 'error' not in summary['results'][0] and 'error' in summary['results'][1]
    if overwrite:assert first.read_bytes()==b'old first' and second.read_bytes()==b'old second'
    else:assert not first.exists() and not second.exists()
    assert not json.loads((tmp_path/'export.report.json').read_text())['committed']


def test_report_publication_failure_rolls_back_ai_and_report(tmp_path,monkeypatch):
    source=tmp_path/'input.pdf';source_pdf(source)
    files=[tmp_path/'export_003.ai',tmp_path/'export_007.ai',tmp_path/'export.report.json']
    for dest in files:dest.write_bytes(b'old')
    real=os.replace
    def fail(source,destination):
        if Path(destination)==files[-1]:raise OSError('report publication failed')
        return real(source,destination)
    monkeypatch.setattr('pdf2ai.batch_publish.os.replace',fail)
    with pytest.raises(OSError,match='report publication'):
        bridge.convert_export({'pdf':str(source),'pages':[3,7],'output':str(tmp_path/'export.ai'),
                               'overwrite':True,'write_report':True})
    assert all(p.read_bytes()==b'old' for p in files)


@pytest.mark.parametrize('strict',[False,True])
def test_preflight_uses_original_page_numbers_without_publishing(tmp_path,strict):
    source=tmp_path/'input.pdf';source_pdf(source,True);events=[]
    summary=bridge.inspect_export({'pdf':str(source),'pages':[3,7],'output':str(tmp_path/'export.ai'),
                                  'strict':strict},events.append)
    assert [r['page'] for r in summary['results']]==[3,7]
    assert [r['native_supported'] for r in summary['results']]==[True,False]
    assert summary['can_export']==(not strict)
    assert events[-1]['current']==2
    assert not list(tmp_path.glob('*.ai')) and not list(tmp_path.glob('*.report.json'))


@pytest.mark.parametrize('action',['success','cancel','timeout','strict','cancel_at_publish'])
@pytest.mark.parametrize('language',['ja','en'])
def test_qt_session_drives_actual_workers_and_protects_output(tmp_path,action,language):
    pytest.importorskip('PySide6.QtWidgets')
    source=tmp_path/'input.pdf';source_pdf(source,unsupported=action=='strict')
    config=tmp_path/'request.json'
    config.write_text(json.dumps({'pdf':str(source),'pages':[3,7],'output':str(tmp_path/'日本語.ai'),
                                 'overwrite':True,'write_report':True,'strict':action=='strict','language':language}))
    old=tmp_path/'日本語_003.ai';old.write_bytes(b'previous')
    code=r'''
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from progress_dialog import ExportSession
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
app=QApplication(['test'])
session=ExportSession(Path(sys.argv[2]),Path(sys.argv[1])/'export_ai.py',approve=lambda summary:True)
action=sys.argv[3]
events=[]
def event(value):
    events.append(value['phase'])
    if value['phase']=='convert' and value['current']==1 and action=='cancel':session.cancel()
    if value['phase']=='inspect' and action=='timeout':
        session.limit=1;session.started-=100;session.check_timeout()
    if value['phase']=='ready_to_publish' and action=='cancel_at_publish':QTimer.singleShot(0,session.cancel)
session.phase_event.connect(event)
QTimer.singleShot(0,session.start)
QTimer.singleShot(15000,lambda:app.exit(9))
session.exec()
print(json.dumps({'summary':session.summary,'events':events},ensure_ascii=False))
'''
    env=bridge.child_environment();env['QT_QPA_PLATFORM']='offscreen'
    result=subprocess.run([sys.executable,'-c',code,str(SCRIPT.parent),str(config),action],
                          env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    data=json.loads(result.stdout);summary=data['summary']
    if action in ('success','cancel_at_publish'):
        assert summary['committed'] and old.read_bytes()!=b'previous'
        assert (tmp_path/'日本語_007.ai').exists() and 'ready_to_publish' in data['events']
    else:
        assert summary['cancelled'] and not summary['committed'] and old.read_bytes()==b'previous'
        assert not (tmp_path/'日本語_007.ai').exists() and not (tmp_path/'日本語.report.json').exists()
        if action=='timeout':assert summary['timed_out']
        if action=='strict':assert summary['preflight_rejected']


def test_preflight_dialog_disables_export_for_strict_blocker(tmp_path):
    pytest.importorskip('PySide6.QtWidgets')
    code=r'''
import sys
sys.path.insert(0,sys.argv[1])
from PySide6.QtWidgets import QApplication,QDialogButtonBox,QPlainTextEdit
from progress_dialog import build_preflight_dialog
app=QApplication(['test'])
dialog=build_preflight_dialog({'can_export':False,'results':[{'page':7,'native_supported':False,'first_blocker':'Hairline'}]})
assert not dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).isEnabled()
assert 'ページ7' in dialog.findChild(QPlainTextEdit).toPlainText()
'''
    env=bridge.child_environment();env['QT_QPA_PLATFORM']='offscreen'
    result=subprocess.run([sys.executable,'-c',code,str(SCRIPT.parent)],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('case', ['clean', 'warning', 'fallback', 'blocked', 'declined'])
def test_preflight_confirmation_only_for_warnings_or_blockers(tmp_path, case):
    pytest.importorskip('PySide6.QtWidgets')
    request = tmp_path/'request.json'
    request.write_text(json.dumps({'pages':[1]}))
    code = r'''
import sys
sys.path.insert(0,sys.argv[1])
from progress_dialog import ExportSession
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QProcess
app=QApplication(['test'])
case=sys.argv[3]
calls=[]
session=ExportSession(sys.argv[2],'unused',approve=lambda summary: calls.append(summary) or case!='declined')
session.mode='inspect'
session.pending={'can_export':case!='blocked','results':[{
    'native_supported':case not in ('fallback','blocked'),
    'warnings':['Text is outlined'] if case in ('warning','declined') else []}]}
started=[]
session.start=lambda mode: started.append(mode)
session.worker_finished(0,QProcess.ExitStatus.NormalExit)
assert bool(calls)==(case!='clean')
assert started==([] if case in ('blocked','declined') else ['worker'])
if case in ('blocked','declined'):
    assert session.summary['preflight_rejected'] and not session.summary['committed']
'''
    env=bridge.child_environment();env['QT_QPA_PLATFORM']='offscreen'
    result=subprocess.run([sys.executable,'-c',code,str(SCRIPT.parent),str(request),case],
                          env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('symlink',[False,True])
def test_cross_filesystem_backup_restoration_after_late_failure(tmp_path,monkeypatch,symlink):
    import errno
    from pdf2ai.batch_publish import publish_batch
    stage=tmp_path/'stage';stage.mkdir()
    destinations=[tmp_path/name for name in ('a.ai','b.ai','c.ai')]
    sources=[stage/name.name for name in destinations]
    for source in sources:source.write_bytes(b'new')
    for destination in destinations:destination.write_bytes(b'old')
    target=tmp_path/'original';target.write_bytes(b'original target')
    if symlink:
        destinations[1].unlink();destinations[1].symlink_to('original')
    real_replace=os.replace
    def simulate_filesystems(source,destination):
        source,destination=Path(source),Path(destination)
        if source.parent==stage and destination==destinations[2]:raise OSError('late publication failure')
        if source.parent.name.startswith('.pdf2ai-recovery-') and destination==destinations[1]:
            raise OSError(errno.EXDEV,'cross-device link')
        return real_replace(source,destination)
    monkeypatch.setattr('pdf2ai.batch_publish.os.replace',simulate_filesystems)
    with pytest.raises(OSError,match='late publication failure'):
        publish_batch(zip(sources,destinations),overwrite=True)
    assert destinations[0].read_bytes()==b'old' and destinations[2].read_bytes()==b'old'
    if symlink:
        assert destinations[1].is_symlink() and os.readlink(destinations[1])=='original'
        assert target.read_bytes()==b'original target'
    else:assert destinations[1].read_bytes()==b'old'
    assert not list(tmp_path.glob('.pdf2ai-*'))
