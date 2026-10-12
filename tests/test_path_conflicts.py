"""Output aliases must be rejected before conversion or batch publication."""
import os

import pikepdf
import pytest

from pdf2ai.batch_publish import publish_batch
from pdf2ai.cli import main
from pdf2ai.multiboard import convert_document
from pdf2ai.native import convert
from pdf2ai.path_conflicts import duplicate_destinations, paths_conflict
from pdf2ai.vector import ConversionError


def source_pdf(path):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Contents=pdf.make_stream(b'10 10 20 20 re f');pdf.save(path)


def require_aliases(tmp_path,names):
    directory=tmp_path/'detect';directory.mkdir()
    (directory/names[0]).touch()
    if not (directory/names[1]).exists():
        pytest.skip('Filesystem treats these names as distinct')


@pytest.mark.parametrize('names',[('Design','design'),('caf\u00e9','cafe\u0301')])
@pytest.mark.parametrize('overwrite',[False,True])
@pytest.mark.parametrize('combined',[False,True])
def test_cli_rejects_filesystem_aliases_before_any_conversion(tmp_path,monkeypatch,names,overwrite,combined):
    require_aliases(tmp_path,names)
    inputs=[]
    for index,name in enumerate(names):
        directory=tmp_path/str(index);directory.mkdir()
        source=directory/(name+'.pdf');source_pdf(source);inputs.append(source)
    output=tmp_path/'output';output.mkdir()
    originals=[source.read_bytes() for source in inputs]
    def forbidden(*args,**kwargs):raise AssertionError('Collision must be detected before conversion')
    monkeypatch.setattr('pdf2ai.cli.convert',forbidden)
    monkeypatch.setattr('pdf2ai.cli.convert_document',forbidden)
    args=[*(str(source) for source in inputs),'--output-dir',str(output)]
    if overwrite:args.append('--overwrite')
    if combined:args.append('--combine')
    assert main(args)==1
    assert not list(output.iterdir())
    assert [source.read_bytes() for source in inputs]==originals


def test_duplicate_check_respects_actual_filesystem_rules_and_cleans_probes(tmp_path):
    directory=tmp_path/'detect';directory.mkdir()
    names=('Design.ai','design.ai')
    (directory/names[0]).touch()
    aliases=(directory/names[1]).exists()
    output=tmp_path/'output';output.mkdir()
    assert duplicate_destinations([output/name for name in names])==aliases
    assert not list(output.iterdir())
    assert not duplicate_destinations([output/'one.ai',output/'two.ai'])
    assert not list(output.iterdir())


@pytest.mark.parametrize('overwrite',[False,True])
def test_batch_rejects_case_aliases_without_publishing(tmp_path,overwrite):
    require_aliases(tmp_path,('Design.ai','design.ai'))
    staging=tmp_path/'staging';staging.mkdir()
    sources=[staging/'one',staging/'two']
    for source in sources:source.write_bytes(b'new')
    output=tmp_path/'output';output.mkdir()
    with pytest.raises(ValueError,match='Duplicate'):
        publish_batch(zip(sources,[output/'Design.ai',output/'design.ai']),overwrite=overwrite)
    assert not list(output.iterdir())
    assert all(source.read_bytes()==b'new' for source in sources)


def test_report_case_alias_does_not_overwrite_planned_ai(tmp_path):
    require_aliases(tmp_path,('result.ai','RESULT.AI'))
    source=tmp_path/'source.pdf';source_pdf(source)
    assert main([str(source),'-o',str(tmp_path/'result.ai'),
                 '--report',str(tmp_path/'RESULT.AI'),'--overwrite'])==1
    assert not (tmp_path/'result.ai').exists()
    assert not list(tmp_path.glob('.pdf2ai-path-check-*'))


@pytest.mark.parametrize('check',[False,True])
def test_report_hardlink_to_input_is_rejected(tmp_path,check):
    source=tmp_path/'source.pdf';source_pdf(source)
    original=source.read_bytes();report=tmp_path/'report.json';os.link(source,report)
    args=[str(source),'--report',str(report),'--overwrite']
    if check:args.append('--check')
    assert paths_conflict(source,report)
    assert main(args)==1
    assert source.read_bytes()==report.read_bytes()==original
    assert not source.with_suffix('.ai').exists()


@pytest.mark.parametrize('combined',[False,True])
def test_api_rejects_hardlink_input_output_conflict(tmp_path,combined):
    source=tmp_path/'source.pdf';source_pdf(source)
    original=source.read_bytes();output=tmp_path/'out.ai';os.link(source,output)
    with pytest.raises(ConversionError,match='must differ'):
        (convert_document if combined else convert)(source,output,overwrite=True)
    assert source.read_bytes()==output.read_bytes()==original
