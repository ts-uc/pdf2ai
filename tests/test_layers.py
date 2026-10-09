"""Optional-content layers, visibility, scoped membership and paint order."""
from pathlib import Path
import pikepdf
import pymupdf
import pytest
from pdf2ai.native import convert,read_private
from pdf2ai.vector import read_drawing,ConversionError


def layer_pdf(path, *, interleaved=False, membership=False):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,100))
    groups=[pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.OCG,Name=n)) for n in ('背景','非表示','文字と図形','空レイヤー')]
    back,hidden,front,empty=groups
    pdf.Root.OCProperties=pikepdf.Dictionary(OCGs=groups,D=pikepdf.Dictionary(BaseState=pikepdf.Name.ON,OFF=[hidden],Locked=[back],Order=list(reversed(groups))))
    prop=pikepdf.Dictionary(Back=back,Hidden=hidden,Front=front)
    if membership: prop.Front=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.OCMD,OCGs=[back,front],P=pikepdf.Name.AnyOn))
    form=pdf.make_stream(b'0 1 0 rg 60 20 70 60 re f')
    form.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Form,BBox=[0,0,200,100],OC=front,Resources=pikepdf.Dictionary()))
    page.obj.Resources=pikepdf.Dictionary(Properties=prop,XObject=pikepdf.Dictionary(F=form))
    contents=b'/OC /Back BDC q 1 0 0 rg 10 10 180 80 re f Q EMC /OC /Hidden BDC 0 0 1 rg 30 20 140 60 re f EMC /OC /Front BDC /Span BMC 1 1 0 rg 70 30 50 40 re f EMC EMC /F Do'
    if interleaved:contents+=b' /OC /Back BDC 0 0 0 rg 80 40 20 20 re f EMC'
    page.obj.Contents=pdf.make_stream(contents);pdf.save(path)


def test_layer_names_visibility_lock_and_form(tmp_path):
    source=tmp_path/'layers.pdf';out=tmp_path/'layers.ai';layer_pdf(source)
    result=convert(source,out)
    assert [l['name'] for l in result['layers']]==['背景','非表示','文字と図形','空レイヤー']
    assert result['layers'][0]['locked']
    assert not result['layers'][1]['visible']
    with pikepdf.open(source) as p:
        d=read_drawing(p.pages[0],root=p.Root)
        assert [item.state.layer.name for item in d.items]==['背景','非表示','文字と図形','文字と図形']
    with pikepdf.open(out) as p:
        body=read_private(p)
        assert body.count(b'%AI5_BeginLayer\r')==4
        assert body.count(b'%AI5_EndLayer--\r')==4
        assert b'0 1 1 0 0 0 1 0 79 128 255 0 50 0 Lb' in body
    with pymupdf.open(source) as a,pymupdf.open(out) as b:
        assert a[0].get_pixmap().samples==b[0].get_pixmap().samples


def test_interleaved_layers_keep_paint_order(tmp_path):
    source=tmp_path/'layers.pdf';out=tmp_path/'layers.ai';layer_pdf(source,interleaved=True)
    result=convert(source,out)
    assert [l['name'] for l in result['layers']]==['背景','非表示','文字と図形','背景 (2)','空レイヤー']
    with pikepdf.open(out) as p:
        body=read_private(p)
        assert body.count(b'%AI5_BeginLayer\r')==5


def test_membership_expression_rejected_atomically(tmp_path):
    source=tmp_path/'layers.pdf';out=tmp_path/'layers.ai';layer_pdf(source,membership=True)
    with pytest.raises(ConversionError,match='OCMD'):convert(source,out,raster_fallback=False)
    assert not out.exists()


def test_ocg_without_document_declaration_rejected(tmp_path):
    source=tmp_path/'layers.pdf';out=tmp_path/'layers.ai';layer_pdf(source)
    with pikepdf.open(source,allow_overwriting_input=True) as p:
        del p.Root['/OCProperties'];p.save(source)
    with pytest.raises(ConversionError,match='OCProperties'):convert(source,out,raster_fallback=False)


def test_outlining_layered_pdf_rejected_before_preprocessing(tmp_path):
    source=tmp_path/'layers.pdf';out=tmp_path/'layers.ai';layer_pdf(source)
    with pytest.raises(ConversionError,match='Text outlining with PDF layers'):
        convert(source,out,outline_text=True,ghostscript='/does/not/exist',raster_fallback=False)
    assert not out.exists()
