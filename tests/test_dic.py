"""DICスウォッチのLab値・濃度と、通常の特色との区別を検証する。"""
import pikepdf
import pytest
import fitz
from pdf2ai.dic import dic_color, _colors
from pdf2ai.native import convert, read_private
from pdf2ai.vector import read_spot, ConversionError


def separation(alternate, function, name='DIC 1s'):
    return pikepdf.Array([pikepdf.Name.Separation,pikepdf.Name('/'+name),alternate,function])


def linear(full, zero):
    return pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=zero,C1=full,N=1)


@pytest.mark.parametrize('calculator',[False,True])
def test_dic_cmyk_pdf_exports_lab_swatch_and_tints(tmp_path,calculator):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,100))
    fn=linear([.2,.3,.4,0],[0]*4)
    if calculator:
        fn=pdf.make_stream(b'{ dup 0.2 mul exch dup 0.3 mul exch dup 0.4 mul exch 0 mul }')
        fn.FunctionType=4;fn.Domain=[0,1];fn.Range=[0,1]*4
    page.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(S=separation(pikepdf.Name.DeviceCMYK,fn)))
    page.Contents=pdf.make_stream(b'/S cs 0.25 scn 10 10 50 50 re f /S CS 0.5 SCN 2 w 80 10 50 50 re S')
    source=tmp_path/'in.pdf';out=tmp_path/'out.ai';pdf.save(source)
    report=convert(source,out,raster_fallback=False)
    assert report['spots'][0]['alternate_space']=='Lab'
    assert report['spots'][0]['values']==pytest.approx([87.0588226318359,12,17])
    with pikepdf.open(out) as ai:
        private=read_private(ai)
        assert b'(DIC 1s) 0 2 Xx\r(DIC 1s)\rPc' in private
        assert b'(DIC 1s) 0.75 2 Xx' in private
        assert b'(DIC 1s) 0.5 2 XX' in private
    with fitz.open(source) as original,fitz.open(out) as ai:
        assert original[0].get_pixmap().samples==ai[0].get_pixmap().samples


@pytest.mark.parametrize('icc',[False,True])
def test_dic_lab_input_preserves_actual_lab_values(icc):
    pdf=pikepdf.new()
    alternate=pikepdf.Array([pikepdf.Name.Lab,pikepdf.Dictionary(WhitePoint=[.964203,1,.824905],Range=[-128,127,-128,127])])
    if icc:
        profile=pdf.make_stream(bytes(16)+b'Lab '+bytes(108));profile.N=3;profile.Alternate=alternate
        alternate=pikepdf.Array([pikepdf.Name.ICCBased,profile])
    spot=read_spot(separation(alternate,linear([86,13,18],[100,0,0])))
    assert spot.lab==(86,13,18)


def test_custom_spot_is_not_replaced_by_similar_dic_name():
    for name in ('DIC test','DIC 1','DIC 4s','My DIC 1s'):
        spot=read_spot(separation(pikepdf.Name.DeviceCMYK,linear([.2,.3,.4,0],[0]*4),name))
        assert spot.lab is None and spot.cmyk==(.2,.3,.4,0)
    assert dic_color('DIC 4s*') is not None
    assert len(_colors())==1280


def test_invalid_dic_tint_is_not_hidden_by_book_lookup():
    with pytest.raises(ConversionError,match='Nonlinear'):
        fn=linear([.2,.3,.4,0],[0]*4);fn.N=2
        read_spot(separation(pikepdf.Name.DeviceCMYK,fn))
