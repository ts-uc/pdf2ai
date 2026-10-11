import pikepdf
import pytest

from pdf2ai.vector import read_image, State, ConversionError
from pdf2ai.native import convert
from pdf2ai.preflight import inspect_document
from test_image_samples import make_image, document


@pytest.mark.parametrize('model,channels',[('DeviceGray',1),('DeviceRGB',3),('DeviceCMYK',4)])
def test_16bit_color_key_remains_strictly_rejected_before_overwrite(tmp_path,model,channels):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    raw=b''.join(value.to_bytes(2,'big')*channels for value in (1000,1001))
    image=make_image(pdf,raw,width=2,bits=16,space='/'+model)
    image.Mask=[1000,1000]*channels
    image.Decode=[1,0]*channels
    with pytest.raises(ConversionError,match='hard image mask'):
        read_image(image,State())
    assert list(image.Mask)==[1000,1000]*channels and list(image.Decode)==[1,0]*channels
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(I=image))
    page.Contents=pdf.make_stream(b'80 0 0 40 10 20 cm /I Do')
    source=tmp_path/'image.pdf';pdf.save(source)
    output=tmp_path/'image.ai';output.write_bytes(b'previous')
    with pytest.raises(ConversionError,match='hard image mask'):
        convert(source,output,overwrite=True,raster_fallback=False)
    assert output.read_bytes()==b'previous'


def test_16bit_decode_is_applied_before_quantization():
    pdf=pikepdf.new()
    raw=b''.join(v.to_bytes(2,'big') for v in (258,65535,0))
    image=make_image(pdf,raw,bits=16)
    image.Decode=[0,.5,1,0,.25,.75]
    assert read_image(image,State()).pixels==bytes([1,0,64])


def test_16bit_soft_mask_decode_is_applied_before_quantization():
    pdf=pikepdf.new()
    image=make_image(pdf,b'\xff\0\0',bits=8)
    mask=make_image(pdf,(258).to_bytes(2,'big'),bits=16,space='/DeviceGray')
    mask.Decode=[0,.5];image.SMask=mask
    assert read_image(image,State()).alpha==b'\x01'
    assert image.SMask.objgen==mask.objgen and list(mask.Decode)==[0,.5]


def test_malformed_indexed_palette_is_a_conversion_diagnostic(tmp_path):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    image=make_image(pdf,b'\0',bits=8)
    image.ColorSpace=pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name.DeviceRGB,0,pikepdf.Name.Bad])
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(I=image))
    page.Contents=pdf.make_stream(b'/I Do')
    source=tmp_path/'invalid.pdf';output=tmp_path/'old.ai';pdf.save(source);output.write_bytes(b'previous')
    with pytest.raises(ConversionError,match='palette'):
        convert(source,output,overwrite=True,raster_fallback=False)
    assert output.read_bytes()==b'previous'
    assert 'palette' in inspect_document(source)[0]['first_blocker']


@pytest.mark.parametrize('space',[[],[pikepdf.Name.Indexed],[pikepdf.Name.ICCBased]])
def test_incomplete_image_color_spaces_are_conversion_diagnostics(space):
    pdf=pikepdf.new();image=make_image(pdf,b'\0',bits=8)
    image.ColorSpace=pikepdf.Array(space)
    with pytest.raises(ConversionError,match='color space array'):
        read_image(image,State())


@pytest.mark.parametrize('dpi',[0,71,1201,float('nan'),float('inf')])
def test_preflight_rejects_invalid_resolution(tmp_path,dpi):
    source=tmp_path/'source.pdf';document(source)
    with pytest.raises(ConversionError,match='DPI'):
        inspect_document(source,raster_dpi=dpi)


def test_preflight_rejects_duplicate_pages_and_reports_vector_plan(tmp_path):
    source=tmp_path/'source.pdf';document(source)
    with pytest.raises(ConversionError,match='selection'):
        inspect_document(source,pages=[1,1])
    assert inspect_document(source,pages=[2])[0]['planned_mode']=='vector'
