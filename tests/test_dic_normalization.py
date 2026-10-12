"""Deep and cyclic unused Form resources must not break DIC normalization."""
import pikepdf
import pytest

from pdf2ai.cli import main
from pdf2ai.dic import normalize_pdf_spots
from pdf2ai.multiboard import convert_document
from pdf2ai.native import convert
from pdf2ai.preflight import inspect_document
from pdf2ai.vector import ConversionError


def nested_pdf(path, depth, *, active=False, cycle=False):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    child=pdf.make_stream(b'/S cs 1 scn 10 10 20 20 re f')
    child.Subtype=pikepdf.Name.Form;child.BBox=[0,0,100,100]
    function=pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0]*4,C1=[.2,.3,.4,0],N=1)
    child.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(S=pikepdf.Array([
        pikepdf.Name.Separation,pikepdf.Name('/DIC 1'),pikepdf.Name.DeviceCMYK,function])))
    if cycle:
        child.Resources.XObject=pikepdf.Dictionary(F=child)
    for _ in range(depth):
        parent=pdf.make_stream(b'/F Do');parent.Subtype=pikepdf.Name.Form;parent.BBox=[0,0,100,100]
        parent.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(F=child));child=parent
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(F=child))
    page.Contents=pdf.make_stream(b'/F Do' if active else b'10 10 20 20 re f')
    pdf.save(path)


@pytest.mark.parametrize('mode', ['single', 'combined', 'cli'])
def test_unused_deep_forms_pass_both_preflight_and_conversion(tmp_path,mode):
    source=tmp_path/'source.pdf';output=tmp_path/'out.ai';nested_pdf(source,1100)
    original=source.read_bytes()
    assert inspect_document(source)[0]['native_supported']
    if mode=='single':
        report=convert(source,output,raster_fallback=False)
        assert not report['rasterized'] and report['spots']==[]
    elif mode=='combined':
        assert not convert_document(source,output,raster_fallback=False)[0]['rasterized']
    else:
        assert main([str(source),'-o',str(output),'--strict'])==0
    assert output.is_file() and source.read_bytes()==original


def test_unused_resource_cycle_terminates_and_normalizes_dic(tmp_path):
    source=tmp_path/'source.pdf';nested_pdf(source,0,cycle=True)
    with pikepdf.open(source) as pdf:
        assert normalize_pdf_spots(pdf.pages[0])==['DIC 1s']
        space=pdf.pages[0].Resources.XObject.F.Resources.ColorSpace.S
        assert str(space[1])=='/DIC 1s'
        assert [float(value) for value in space[3].C1]==[0,.16,.17,0]
    assert not convert(source,tmp_path/'out.ai',raster_fallback=False)['rasterized']


def test_active_deep_forms_still_reject_strict_and_allow_fallback(tmp_path):
    source=tmp_path/'source.pdf';output=tmp_path/'out.ai';nested_pdf(source,40,active=True)
    assert not inspect_document(source)[0]['native_supported']
    output.write_bytes(b'previous')
    with pytest.raises(ConversionError,match='nested Form'):
        convert(source,output,overwrite=True,raster_fallback=False)
    assert output.read_bytes()==b'previous'
    assert convert(source,output,overwrite=True,raster_dpi=72)['rasterized']
