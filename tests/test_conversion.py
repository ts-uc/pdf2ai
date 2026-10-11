from pathlib import Path
import re
import pikepdf
import pytest
import fitz
from pdf2ai.native import convert, read_private
from pdf2ai.vector import ConversionError


def make_pdf(path,content,resources=None,pages=1):
    pdf=pikepdf.new()
    for _ in range(pages):
        page=pdf.add_blank_page(page_size=(200,100))
        page.obj.Contents=pdf.make_stream(content)
        page.obj.Resources=resources or pikepdf.Dictionary()
    pdf.save(path)


def test_transform_compound_and_preview(tmp_path):
    source=tmp_path/'a.pdf';output=tmp_path/'a.ai'
    make_pdf(source,b'q 1 0 0 1 10 20 cm 0 0 0 1 k 0 0 40 40 re 10 10 20 20 re f* Q')
    result=convert(source,output)
    assert result['subpaths']==2
    with pikepdf.open(output) as pdf:
        private=read_private(pdf)
        assert b'10 20 m' in private and b'1 XR' in private
        assert b'*u\r' in private and b'*U\r' in private
        info=pdf.pages[0].obj.PieceInfo.Illustrator.Private
        assert info.RoundtripVersion==24 and info.CreatorVersion==24
    with fitz.open(source) as a,fitz.open(output) as b:
        assert a[0].get_pixmap().samples==b[0].get_pixmap().samples


def test_spot_tint_and_graphics_state(tmp_path):
    source=tmp_path/'a.pdf';output=tmp_path/'a.ai'
    # A type-2 color alternates between CMYK white and the solid ink value.
    spot=pikepdf.Array([pikepdf.Name.Separation,pikepdf.Name('/DIC test'),pikepdf.Name.DeviceCMYK,
                       pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0,0,0,0],C1=[0.2,0.3,0.4,0],N=1)])
    resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(S=spot))
    make_pdf(source,b'/S cs 0.25 scn q 0 0 0 1 k 0 0 10 10 re f Q 20 0 10 10 re f',resources)
    report=convert(source,output)
    assert report['spots'][0]['name']=='DIC test'
    with pikepdf.open(output) as pdf:
        private=read_private(pdf)
        assert b'(DIC test) 0.75 x' in private
        assert b'(DIC test) 0 x\r(DIC test)\rPc' in private
        assert b'0 0 0 1 k' in private


@pytest.mark.parametrize('content',[b'BT /F1 12 Tf (text) Tj ET',b'/I Do',b'/Sh sh',b'Q'])
def test_unsupported_does_not_write(tmp_path,content):
    source=tmp_path/'a.pdf';out=tmp_path/'a.ai';make_pdf(source,content)
    with pytest.raises(ConversionError):convert(source,out,raster_fallback=False)
    assert not out.exists()


def test_multipage_and_no_overwrite(tmp_path):
    source=tmp_path/'a.pdf';out=tmp_path/'a.ai';make_pdf(source,b'0 0 10 10 re f',pages=2)
    with pytest.raises(ConversionError,match='Multipage'):convert(source,out,raster_fallback=False)
    convert(source,out,page_number=2)
    before=out.read_bytes()
    with pytest.raises(ConversionError,match='already exists'):convert(source,out,page_number=1,raster_fallback=False)
    assert out.read_bytes()==before
    with pytest.raises(ConversionError):convert(source,source,overwrite=True,raster_fallback=False)


def test_stroke_scale_and_nonuniform_rejection(tmp_path):
    source=tmp_path/'s.pdf';out=tmp_path/'s.ai'
    make_pdf(source,b'q 2 0 0 2 0 0 cm 3 w [4 2] 1 d 0 0 m 10 10 l S Q')
    convert(source,out)
    with pikepdf.open(out) as pdf:
        body=read_private(pdf)
        assert b'6 w' in body and b'[8 4] 2 d' in body and b'20 20 L' in body
    before=out.read_bytes()
    make_pdf(source,b'q 2 0 0 1 0 0 cm 0 0 m 10 10 l S Q')
    with pytest.raises(ConversionError,match='Nonuniform'):convert(source,out,overwrite=True,raster_fallback=False)
    assert out.read_bytes()==before


SAMPLES=Path(__file__).resolve().parents[1]/'sample'
@pytest.mark.parametrize('kind,page', [('native',1)] + [('pages',n) for n in range(1,5)] + [('fallback',n) for n in range(1,10)])
def test_unified_samples(tmp_path,kind,page):
    source=SAMPLES/('conversion_'+kind+'.pdf')
    out=tmp_path/(kind+str(page)+'.ai')
    result=convert(source,out,page_number=page,raster_dpi=144)
    assert result['rasterized']==(kind=='fallback')
    if kind=='native':
        assert result['gradients']==10 and result['images']==17 and len(result['spots'])==4
        assert result['outlined_glyphs']>1000
    with pikepdf.open(out) as generated:
        assert read_private(generated)
        assert generated.pages[0].obj.PieceInfo.Illustrator.Private.CreatorVersion==24
    with fitz.open(source) as original,fitz.open(out) as generated:
        matrix=fitz.Matrix(0.35,0.35) if kind=='native' else fitz.Matrix(1,1)
        assert original[page-1].get_pixmap(matrix=matrix).samples==generated[0].get_pixmap(matrix=matrix).samples


def test_zero_width_fill_and_overprint(tmp_path):
    source=tmp_path/'a.pdf';out=tmp_path/'a.ai'
    resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(OP=pikepdf.Dictionary(OP=True,op=True,OPM=1)))
    make_pdf(source,b'0 w /OP gs 0 0 0 0.9 k 0 0 10 10 re f',resources)
    convert(source,out)
    with pikepdf.open(out) as pdf:
        body=read_private(pdf)
        assert b'1 O\r0 0 0 0.9 k' in body and b'1 w' in body
    before=out.read_bytes()
    make_pdf(source,b'0 w 0 0 m 10 10 l S')
    with pytest.raises(ConversionError,match='hairline'):convert(source,out,overwrite=True,raster_fallback=False)
    assert out.read_bytes()==before


def test_process_overprint_mode_zero_rejected(tmp_path):
    source=tmp_path/'a.pdf';out=tmp_path/'a.ai'
    resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(OP=pikepdf.Dictionary(OP=True,OPM=0)))
    make_pdf(source,b'/OP gs 0 0 0 1 k 0 0 10 10 re f',resources)
    with pytest.raises(ConversionError,match='mode 0'):convert(source,out,raster_fallback=False)
    assert not out.exists()


@pytest.mark.parametrize('with_alpha',[False,True])
def test_image_pixels_alpha_transform_and_clipping(tmp_path,with_alpha):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    rgb=bytes([255,0,0,0,255,0,0,0,255,255,255,255]);alpha=bytes([0,85,170,255])
    mask=pdf.make_stream(alpha);mask.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject,Subtype=pikepdf.Name.Image,Width=2,Height=2,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray))
    image=pdf.make_stream(rgb);image.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject,Subtype=pikepdf.Name.Image,Width=2,Height=2,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceRGB))
    if with_alpha:image.SMask=mask
    page.obj.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image))
    page.obj.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
    page.obj.Contents=pdf.make_stream(b'q 10 20 40 60 re W n 40 0 0 60 10 20 cm /Im Do Q')
    source=tmp_path/'image.pdf';out=tmp_path/'image.ai';pdf.save(source)
    result=convert(source,out)
    assert result['images']==1 and result['image_soft_masks']==int(with_alpha) and result['color_model']=='RGB'
    with pikepdf.open(out) as generated:
        body=read_private(generated)
        assert b'XI\n'+rgb+(alpha if with_alpha else bytes([255])*4) in body
        assert b'[ 20 0 0 30 10 80 ]' in body
        assert b'h\rW\rn' in body
        if with_alpha:assert generated.pages[0].Resources.XObject.Im.SMask.read_bytes()==alpha
        else:assert b'8 3 1 17 1 0 4 4 0 0' in body
    with fitz.open(source) as a,fitz.open(out) as b:
        assert a[0].get_pixmap().samples==b[0].get_pixmap().samples


def test_opacity_blend_and_stroke_visibility(tmp_path):
    source=tmp_path/'a.pdf';out=tmp_path/'a.ai'
    resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(Alpha=pikepdf.Dictionary(ca=0.5),Multiply=pikepdf.Dictionary(BM=pikepdf.Name.Multiply,ca=1)))
    make_pdf(source,b'q /Alpha gs 1 0 0 rg 0 0 10 10 re f Q 0 0 10 10 re S q /Multiply gs 0 1 0 rg 5 5 10 10 re f Q',resources)
    convert(source,out)
    with pikepdf.open(out) as pdf:
        body=read_private(pdf)
        assert b'0 0.5 0 0 0 Xy' in body
        assert b'1 1 0 0 0 Xy' in body
        assert b'0 1 0 0 0 Xy' in body
        assert b'0 1 1 0 1 0 0 Xa' in body


def test_unsupported_transparency_still_rejected(tmp_path):
    source=tmp_path/'a.pdf';out=tmp_path/'a.ai'
    resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(Screen=pikepdf.Dictionary(BM=pikepdf.Name.Nonstandard)))
    make_pdf(source,b'/Screen gs 0 0 10 10 re f',resources)
    with pytest.raises(ConversionError,match='blend mode'):convert(source,out,raster_fallback=False)
    assert not out.exists()


def test_editable_gradient_pattern_and_matrix(tmp_path):
    source=tmp_path/'gradient.pdf';out=tmp_path/'gradient.ai'
    function=pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0,0,1],C1=[0,1,0],N=1)
    shading=pikepdf.Dictionary(ShadingType=2,ColorSpace=pikepdf.Name.DeviceRGB,
                              Coords=[0,0,40,0],Extend=[True,True],Function=function)
    pattern=pikepdf.Dictionary(PatternType=2,Matrix=[0,1,-1,0,20,30],Shading=shading)
    resources=pikepdf.Dictionary(Pattern=pikepdf.Dictionary(P=pattern))
    make_pdf(source,b'q 1 0 0 1 80 0 cm /Pattern cs /P scn 0 0 40 40 re f Q',resources)
    result=convert(source,out)
    assert result['gradients']==1
    with pikepdf.open(out) as pdf:
        body=read_private(pdf)
        assert b'1 (PDF gradient 1) 0.75 0 90 1 1 0 0 1 0 0 1 Bg' in body
        assert b'0 40 40 0 20 30 Xm' in body
        assert b'(PDF gradient 1) 0 2 Bd' in body and b'2 1 6 50 100 %_BS' in body
    before=out.read_bytes()
    function.N=-1
    make_pdf(source,b'/Pattern cs /P scn 0 0 40 40 re f',resources)
    with pytest.raises(ConversionError,match='positive exponential'):convert(source,out,overwrite=True,raster_fallback=False)
    assert out.read_bytes()==before


def test_cli_rejects_ai_as_input(tmp_path):
    from pdf2ai.cli import main
    source=tmp_path/'reference.ai';source.write_bytes(b'reference')
    assert main([str(source),'--overwrite'])==1
    assert source.read_bytes()==b'reference'


@pytest.mark.parametrize('rasterized',[False,True])
def test_illustrator_creator_and_producer_metadata(tmp_path,rasterized):
    from pdf2ai.native import AI_CREATOR, AI_PRODUCER
    source=tmp_path/'input.pdf';output=tmp_path/'output.ai'
    make_pdf(source,b'10 10 30 30 re f')
    with pikepdf.open(source,allow_overwriting_input=True) as pdf:
        pdf.docinfo['/Creator']='Scribus'
        pdf.docinfo['/Producer']='Original PDF writer'
        pdf.docinfo['/Title']='Artwork'
        pdf.docinfo['/Author']='Designer'
        if rasterized:
            pdf.pages[0].Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,K=True,CS=pikepdf.Name.DeviceCMYK)
        with pdf.open_metadata(set_pikepdf_as_editor=False,update_docinfo=False) as metadata:
            metadata['xmp:CreatorTool']='Scribus'
            metadata['pdf:Producer']='Original PDF writer'
        pdf.save(source)
    report=convert(source,output,raster_dpi=72)
    assert report['rasterized']==rasterized
    with pikepdf.open(output) as pdf:
        assert str(pdf.docinfo['/Creator'])==AI_CREATOR
        assert str(pdf.docinfo['/Producer'])==AI_PRODUCER
        assert str(pdf.docinfo['/Title'])=='Artwork'
        assert str(pdf.docinfo['/Author'])=='Designer'
        with pdf.open_metadata(set_pikepdf_as_editor=False) as metadata:
            assert metadata['xmp:CreatorTool']==AI_CREATOR
            assert metadata['pdf:Producer']==AI_PRODUCER
        private=read_private(pdf)
        assert b'%%Creator: Adobe Illustrator(R) 24.0' in private
        assert b'pdf2ai-vector' not in private
