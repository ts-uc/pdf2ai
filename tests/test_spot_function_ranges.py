"""Do not silently discard clipping in a Separation tint function."""
import pikepdf
import pytest

from pdf2ai.native import convert
from pdf2ai.multiboard import convert_document
from pdf2ai.preflight import inspect_document
from pdf2ai.vector import ConversionError, read_spot


def separation(pdf,name='Custom',calculator=False):
    if calculator:
        fn=pdf.make_stream(b'{ dup 1 mul exch dup 0 mul exch dup 0 mul exch 0 mul }')
        fn.update(pikepdf.Dictionary(FunctionType=4,Domain=[0,1],Range=[0,.2,0,1,0,1,0,1]))
    else:
        fn=pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0]*4,C1=[1,0,0,0],N=1,
                             Range=[0,.2,0,1,0,1,0,1])
    return pikepdf.Array([pikepdf.Name.Separation,pikepdf.Name('/'+name),pikepdf.Name.DeviceCMYK,fn])


@pytest.mark.parametrize('calculator',[False,True])
@pytest.mark.parametrize('name',['Custom','DIC 1','CF 10001'])
def test_clipping_range_is_not_hidden_by_book_normalization(tmp_path,calculator,name):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    space=separation(pdf,name,calculator)
    page.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(Spot=space))
    page.Contents=pdf.make_stream(b'/Spot cs 1 scn 10 10 80 80 re f')
    source=tmp_path/'source.pdf';pdf.save(source)
    assert not inspect_document(source)[0]['native_supported']
    for function in (convert,convert_document):
        output=tmp_path/'out.ai';output.write_bytes(b'previous')
        with pytest.raises(ConversionError,match='range'):
            function(source,output,overwrite=True,raster_fallback=False)
        assert output.read_bytes()==b'previous'
        result=function(source,output,overwrite=True)
        row=result[0] if isinstance(result,list) else result
        assert row['rasterized']
        with pikepdf.open(output) as ai:
            assert list(ai.pages[0].Resources.ColorSpace.Spot[3].Range)==list(space[3].Range)


@pytest.mark.parametrize('calculator',[False,True])
def test_range_containing_all_linear_tints_remains_supported(calculator):
    pdf=pikepdf.new();space=separation(pdf,calculator=calculator)
    space[3].Range=[0,1]*4
    assert read_spot(space).cmyk==(1,0,0,0)


@pytest.mark.parametrize('bounds',[[0,1], [0,1]*3, [1,0]*4])
def test_invalid_function_range_is_rejected(bounds):
    pdf=pikepdf.new();space=separation(pdf)
    space[3].Range=bounds
    with pytest.raises(ConversionError,match='range'):
        read_spot(space)


@pytest.mark.parametrize('limits',[[0,100,-128,127,-128,127], [0,90,-128,127,-128,127]])
def test_lab_function_range_also_checks_paper_white(limits):
    space=pikepdf.Array([pikepdf.Name.Separation,pikepdf.Name('/CF 10001'),
        pikepdf.Array([pikepdf.Name.Lab,pikepdf.Dictionary(WhitePoint=[.964203,1,.824905])]),
        pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[100,0,0],C1=[44,55,-16],N=1,
                           Range=limits)])
    if limits[1]==100:
        assert read_spot(space).lab==(44,55,-16)
    else:
        with pytest.raises(ConversionError,match='range'):
            read_spot(space)


@pytest.mark.parametrize('limits',[[-20,20,-128,127], [1,100,-128,127], [0,1]])
def test_lab_color_space_range_cannot_silently_clip_tints(limits):
    space=pikepdf.Array([pikepdf.Name.Separation,pikepdf.Name('/CF 10001'),
        pikepdf.Array([pikepdf.Name.Lab,pikepdf.Dictionary(WhitePoint=[.964203,1,.824905],Range=limits)]),
        pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[100,0,0],C1=[44,55,-16],N=1)])
    with pytest.raises(ConversionError,match='range'):
        read_spot(space)
