"""Native font outlines, image samples and opt-in strict conversion guarantees."""
from io import BytesIO
from pathlib import Path
import pikepdf
import pymupdf
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from pdf2ai.native import convert,read_private,make_private
from pdf2ai.vector import ConversionError,read_drawing
from test_common_features import feature_pdf


def true_type_pdf(path):
    builder=FontBuilder(1000,isTTF=True);builder.setupGlyphOrder(['.notdef','space','A','B'])
    glyphs={}
    for name in ('.notdef','space','A','B'):
        pen=TTGlyphPen(None)
        if name in ('A','B'):
            pen.moveTo((0,0));pen.lineTo((500,0));pen.lineTo((500,700));pen.lineTo((0,700));pen.closePath()
        glyphs[name]=pen.glyph()
    builder.setupGlyf(glyphs);builder.setupHorizontalMetrics({n:(600,0) for n in glyphs})
    builder.setupHorizontalHeader(ascent=800,descent=-200);builder.setupCharacterMap({32:'space',65:'A',66:'B'})
    builder.setupNameTable({'familyName':'Fixture','styleName':'Regular','uniqueFontIdentifier':'Fixture','fullName':'Fixture','psName':'Fixture'})
    builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
    builder.setupPost();buffer=BytesIO();builder.save(buffer)
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,100))
    program=pdf.make_stream(buffer.getvalue())
    descriptor=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.FontDescriptor,FontName=pikepdf.Name.Fixture,Flags=32,FontBBox=[0,0,500,700],ItalicAngle=0,Ascent=800,Descent=-200,CapHeight=700,StemV=80,FontFile2=program))
    mapping=bytearray(134);mapping[130:132]=b'\0\2';mapping[132:134]=b'\0\3'
    descendant=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.CIDFontType2,BaseFont=pikepdf.Name.Fixture,CIDSystemInfo=pikepdf.Dictionary(Registry=pikepdf.String('Adobe'),Ordering=pikepdf.String('Identity'),Supplement=0),FontDescriptor=descriptor,CIDToGIDMap=pdf.make_stream(bytes(mapping)),W=[65,[600,600]],DW=600))
    font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type0,BaseFont=pikepdf.Name.Fixture,Encoding=pikepdf.Name('/Identity-H'),DescendantFonts=[descendant]))
    layer=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.OCG,Name='Embedded text'))
    pdf.Root.OCProperties=pikepdf.Dictionary(OCGs=[layer],D=pikepdf.Dictionary(BaseState=pikepdf.Name.ON))
    page.obj.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F=font),Properties=pikepdf.Dictionary(L=layer))
    page.obj.Contents=pdf.make_stream(b'/OC /L BDC BT /F 20 Tf 1 0 0 1 20 50 Tm [<0041> -120 <0042>] TJ ET EMC')
    pdf.save(path)


def test_embedded_cid_text_with_layers_and_kerning(tmp_path):
    source=tmp_path/'font.pdf';output=tmp_path/'font.ai';true_type_pdf(source)
    result=convert(source,output,raster_fallback=False)
    assert result['outlined_glyphs']==2 and not result['rasterized']
    assert result['layers'][0]['name']=='Embedded text'
    with pikepdf.open(output) as pdf:
        body=read_private(pdf)
        assert b'20 50 m' in body and b'34.4 50 m' in body
        assert b'30 64 L' in body and b'44.4 64 L' in body


def test_standard_text_clipping_and_rotation(tmp_path):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,100))
    font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica))
    page.obj.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F=font))
    page.obj.Contents=pdf.make_stream(b'BT /F 20 Tf 0 1 -1 0 90 30 Tm 7 Tr (AB) Tj ET 1 0 0 rg 0 0 200 100 re f')
    source=tmp_path/'clip.pdf';output=tmp_path/'clip.ai';pdf.save(source)
    result=convert(source,output,raster_fallback=False)
    assert not result['rasterized'] and result['clipping_paths']>=2
    with pikepdf.open(source) as p:
        drawing=read_drawing(p.pages[0]);assert drawing.paths[0].state.clips


@pytest.mark.parametrize('bits,decode',[(8,True),(16,False)])
def test_gray_image_precision_and_decode(tmp_path,bits,decode):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    image=pdf.make_stream(b'\0\xff' if bits==8 else b'\0\0\xff\xff')
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=2,Height=1,BitsPerComponent=bits,ColorSpace=pikepdf.Name.DeviceGray))
    if decode:image.Decode=[1,0]
    page.obj.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(I=image));page.obj.Contents=pdf.make_stream(b'q 80 0 0 40 10 20 cm /I Do Q')
    source=tmp_path/'image.pdf';output=tmp_path/'image.ai';pdf.save(source)
    result=convert(source,output,raster_fallback=False)
    assert not result['rasterized']
    with pikepdf.open(source) as p:
        drawing=read_drawing(p.pages[0]);assert drawing.images[0].pixels==(b'\xff\0' if decode else b'\0\xff')
    with pikepdf.open(output) as p:
        body=read_private(p)
        assert b'/DeviceRGB XN' in body
        assert b'XI\n'+(b'\xff\xff\xff\0\0\0' if decode else b'\0\0\0\xff\xff\xff') in body


def test_stencil_as_native_paths(tmp_path):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    image=pdf.make_stream(b'\x50\x50')
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=4,Height=2,BitsPerComponent=1,ImageMask=True))
    page.obj.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(I=image))
    page.obj.Contents=pdf.make_stream(b'q 0 1 0 rg 80 0 0 40 10 20 cm /I Do Q')
    source=tmp_path/'stencil.pdf';output=tmp_path/'stencil.ai';pdf.save(source)
    result=convert(source,output,raster_fallback=False)
    assert result['subpaths']==2 and result['images']==0
    with pikepdf.open(output) as p:assert b'10 20 m' in read_private(p)


def test_nonlinear_gradient_as_editable_stops(tmp_path):
    source=tmp_path/'gradient.pdf';output=tmp_path/'gradient.ai';feature_pdf(source)
    with pikepdf.open(source,allow_overwriting_input=True) as p:
        p.pages[0].Resources.Shading.Radial.Function.N=2;p.save(source)
    result=convert(source,output,raster_fallback=False)
    assert result['gradients']==1 and not result['rasterized']
    with pikepdf.open(source) as p:
        gradient=read_drawing(p.pages[0]).paths[0].state.fill
        assert len(gradient.stops)>10
        for (a,ca),(b,cb) in zip(gradient.stops,gradient.stops[1:]):
            midpoint=(a+b)/2
            assert abs((ca.values[1]+cb.values[1])/2-(1-midpoint**2))<0.25/255


def test_automatic_fallback_retains_pdf_and_declares_losses(tmp_path):
    source=tmp_path/'fallback.pdf';output=tmp_path/'fallback.ai';feature_pdf(source)
    with pikepdf.open(source,allow_overwriting_input=True) as p:
        p.pages[0].Contents=pikepdf.Array([p.pages[0].Contents,p.make_stream(b'q 0 w 10 10 m 50 50 l S Q')]);p.save(source)
    result=convert(source,output,raster_dpi=144)
    assert result['rasterized'] and result['conversion_mode']=='raster-fallback'
    assert result['images']==1 and result['raster_dpi']==144 and result['lost_features']
    assert 'hairline' in result['fallback_reason']
    with pikepdf.open(output) as p:
        body=read_private(p);assert b'XI\n' in body
        assert p.pages[0].obj.PieceInfo.Illustrator.Private.CreatorVersion==24
    with pymupdf.open(source) as a,pymupdf.open(output) as b:
        assert a[0].get_pixmap().samples==b[0].get_pixmap().samples
    previous=output.read_bytes()
    with pytest.raises(ConversionError):convert(source,output,overwrite=True,raster_fallback=False)
    assert output.read_bytes()==previous


@pytest.mark.parametrize('dpi',[0,71,1201,float('nan')])
def test_bad_dpi_never_creates_output(tmp_path,dpi):
    source=tmp_path/'a.pdf';output=tmp_path/'a.ai';feature_pdf(source)
    with pytest.raises(ConversionError,match='DPI'):convert(source,output,raster_dpi=dpi)
    assert not output.exists()


def test_fallback_memory_limit(tmp_path):
    source=tmp_path/'a.pdf';output=tmp_path/'a.ai';feature_pdf(source)
    with pikepdf.open(source,allow_overwriting_input=True) as p:
        p.pages[0].Contents=pikepdf.Array([p.pages[0].Contents,p.make_stream(b'q 0 w 10 10 m 50 50 l S Q')]);p.save(source)
    with pytest.raises(ConversionError,match='million pixels'):convert(source,output,raster_dpi=1200)
    assert not output.exists()


@pytest.mark.parametrize('mode',[4,5,6,7])
def test_whitespace_text_clip_has_empty_area(mode):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F=pikepdf.Dictionary(
        Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica)))
    page.Contents=pdf.make_stream(b'BT /F 20 Tf '+str(mode).encode()+
        b' Tr ( ) Tj 0 Tr ET 1 0 0 rg 0 0 100 100 re f')
    drawing=read_drawing(page)
    clips=drawing.paths[-1].state.clips
    assert len(clips)==2
    assert all(len(clip.paths)==1 and clip.paths[0].closed for clip in clips)
    first_x=[coords[0] for _,coords in clips[0].paths[0].commands]
    second_x=[coords[0] for _,coords in clips[1].paths[0].commands]
    assert max(first_x)<min(second_x)
    _,private=make_private(drawing,'space.pdf')
    assert private.count(b'\rW\rn')==2


@pytest.mark.parametrize('text',[b'() Tj',b''])
def test_clipping_mode_without_any_character_does_not_add_clip(text):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F=pikepdf.Dictionary(
        Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica)))
    page.Contents=pdf.make_stream(b'BT /F 20 Tf 7 Tr '+text+b' ET 1 0 0 rg 0 0 100 100 re f')
    assert not read_drawing(page).paths[-1].state.clips
