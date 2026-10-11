import pikepdf
import pytest

from pdf2ai.vector import read_image, State, ConversionError
from pdf2ai.native import convert
from pdf2ai.multiboard import convert_document
from pdf2ai.cancellation import ConversionCancelled


def make_image(pdf, raw, width=1, height=1, bits=1, space='/DeviceRGB'):
    image=pdf.make_stream(raw)
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=width,Height=height,
                                   BitsPerComponent=bits,ColorSpace=pikepdf.Name(space)))
    return image


@pytest.mark.parametrize('bits,raw,expected',[
    (1,b'\xa0\x40',bytes([255,0,255,0,255,0])),
    (2,b'\x1c\xb0',bytes([0,85,255,170,255,0])),
    (4,b'\x08\xf0\xf8\x00',bytes([0,136,255,255,136,0])),
])
def test_packed_rgb_rows_and_padding(bits,raw,expected):
    pdf=pikepdf.new()
    image=make_image(pdf,raw,height=2,bits=bits)
    assert read_image(image,State()).pixels==expected


def test_packed_cmyk_decode_and_color_key_use_original_samples():
    pdf=pikepdf.new()
    image=make_image(pdf,b'\x05\xaf',width=2,bits=2,space='/DeviceCMYK')
    image.Decode=[1,0]*4
    image.Mask=[0,0,0,0,1,1,1,1]
    result=read_image(image,State())
    assert result.pixels==bytes([255,255,170,170,85,85,0,0])
    assert result.alpha==bytes([0,255])
    assert list(image.Decode)==[1,0]*4 and list(image.Mask)==[0,0,0,0,1,1,1,1]


@pytest.mark.parametrize('lookup_stream',[False,True])
def test_indexed_decode_reversal_clamping_rounding_and_original_key(lookup_stream):
    pdf=pikepdf.new()
    palette=b'\xff\0\0\0\xff\0\0\0\xff'
    image=make_image(pdf,b'\x1b',width=4,bits=2)
    image.ColorSpace=pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name.DeviceRGB,2,
                                  pdf.make_stream(palette) if lookup_stream else pikepdf.String(palette)])
    image.Decode=[2,-1]
    image.Mask=[1,1]
    result=read_image(image,State())
    assert result.pixels==b'\0\0\xff\0\xff\0\xff\0\0\xff\0\0'
    assert result.alpha==bytes([255,0,255,255])
    assert list(image.Decode)==[2,-1]


def test_invalid_packed_image_restores_pdf_attributes():
    pdf=pikepdf.new()
    image=make_image(pdf,b'',bits=2)
    image.Decode=[1,0]*3
    with pytest.raises(ConversionError,match='sample length'):
        read_image(image,State())
    assert list(image.Decode)==[1,0]*3


def document(path):
    pdf=pikepdf.new()
    for _ in range(3):
        page=pdf.add_blank_page(page_size=(100,100))
        page.Contents=pdf.make_stream(b'1 0 0 rg 10 10 20 20 re f')
    pdf.save(path)


def test_combined_cancel_between_pages_keeps_previous_output(tmp_path):
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai'
    document(source);output.write_bytes(b'previous')
    processed=[]
    with pytest.raises(ConversionCancelled):
        convert_document(source,output,overwrite=True,cancelled=lambda:bool(processed),
                         progress=lambda page,done,total: processed.append((page,done,total)))
    assert processed==[(1,1,3)] and output.read_bytes()==b'previous'


def test_single_cancel_before_save_is_not_raster_fallback(tmp_path,monkeypatch):
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai'
    document(source);output.write_bytes(b'previous')
    import pdf2ai.native as native
    original=native.make_private
    stopped=[]
    def serialize(*args,**kwargs):
        result=original(*args,**kwargs);stopped.append(True);return result
    monkeypatch.setattr(native,'make_private',serialize)
    with pytest.raises(ConversionCancelled):
        convert(source,output,page_number=1,overwrite=True,cancelled=lambda:bool(stopped))
    assert output.read_bytes()==b'previous'


def test_combination_normalizes_cmyk_images_when_destination_is_rgb(tmp_path,monkeypatch):
    pdf=pikepdf.new()
    first=pdf.add_blank_page(page_size=(100,100))
    first.Contents=pdf.make_stream(b'1 0 0 rg 10 10 20 20 re f')
    second=pdf.add_blank_page(page_size=(100,100))
    image=make_image(pdf,b'\0\xff\xff\0',bits=8,space='/DeviceCMYK')
    second.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(I=image))
    second.Contents=pdf.make_stream(b'40 0 0 40 10 10 cm /I Do')
    source=tmp_path/'mixed.pdf';pdf.save(source)
    import pdf2ai.multiboard as multiboard
    original=multiboard.make_private
    merged=[]
    def serialize(drawing,*args,**kwargs):
        if kwargs.get('artboards'):merged.append(drawing)
        return original(drawing,*args,**kwargs)
    monkeypatch.setattr(multiboard,'make_private',serialize)
    reports=convert_document(source,tmp_path/'mixed.ai',raster_fallback=False)
    assert merged[0].images[0].model=='RGB'
    assert reports[1]['combined_color_model']=='RGB'
    assert any('combined AI' in value for value in reports[1]['color_conversions'])


def test_combination_rejects_conflicting_transparency_space_before_overwrite(tmp_path):
    from test_color_transparency import group_scene
    pdf=group_scene(True)
    page=pdf.add_blank_page(page_size=(100,100))
    form=pdf.make_stream(b'0 0 0 1 k 10 10 20 20 re f')
    form.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Form,BBox=[0,0,100,100],
                Resources=pikepdf.Dictionary(),Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceCMYK)))
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(F=form))
    page.Contents=pdf.make_stream(b'/F Do')
    source=tmp_path/'mixed.pdf';output=tmp_path/'mixed.ai'
    pdf.save(source);output.write_bytes(b'previous')
    with pytest.raises(ConversionError,match='透明グループ色空間'):
        convert_document(source,output,overwrite=True,raster_fallback=False)
    assert output.read_bytes()==b'previous'
