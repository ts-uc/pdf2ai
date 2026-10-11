"""Regression tests for editable geometry and newly supported PDF resources."""
import pikepdf
import pytest

from pdf2ai.native import axial_geometry, convert, make_private, read_private
from pdf2ai.multiboard import translate_drawing
from pdf2ai.vector import Color, Drawing, Gradient, PaintedPath, State, Subpath, point, read_drawing


def rectangle(x0,y0,x1,y1):
    return Subpath([('m',(x0,y0)),('L',(x1,y0)),('L',(x1,y1)),('L',(x0,y1))],True)


def test_axial_ramp_preserves_offset_and_length_in_normalized_geometry():
    g=Gradient('vertical',((0,Color('RGB',(0,0,1))),(1,Color('RGB',(1,0,0)))),(200,-50),(200,270))
    item=PaintedPath([rectangle(30,30,350,160)],State(fill=g),'fill',False,1)
    offset,angle,length=axial_geometry(item,g)
    assert (offset,angle,length)==pytest.approx((-80/130,90,320/130))
    # The ramp at the carrier's lower/upper edges must match PDF's t.
    assert (0-offset)/length==pytest.approx((30+50)/320)
    assert (1-offset)/length==pytest.approx((160+50)/320)
    _,private=make_private(Drawing((0,0,400,240),[item],[],{},color_model='RGB'),'test')
    assert b'-0.61538462 0 90 2.46153846 1 0 0 1 0 0 1 Bg' in private


def test_gradient_uses_curve_extrema_instead_of_control_polygon_bounds():
    path=Subpath([('m',(0,0)),('C',(0,100,100,100,100,0)),('L',(0,0))],True)
    g=Gradient('curve',((0,Color('RGB',(0,0,0))),(1,Color('RGB',(1,1,1)))),(0,0),(0,75))
    item=PaintedPath([path],State(fill=g),'fill',False,1)
    assert axial_geometry(item,g)==pytest.approx((0,90,1))


@pytest.mark.parametrize('matrix',[(2,.5,.7,1,20,-30),(2,0,0,.5,0,0),(-1,0,0,1,400,0)])
def test_affine_axial_gradient_matches_pdf_ramp_everywhere(tmp_path,matrix):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(400,200))
    fn=pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0,0,1],C1=[1,0,0],N=1)
    shading=pikepdf.Dictionary(ShadingType=2,ColorSpace=pikepdf.Name.DeviceRGB,Coords=[10,20,170,90],Extend=[True,True],Function=fn)
    page.Resources=pikepdf.Dictionary(Pattern=pikepdf.Dictionary(P=pikepdf.Dictionary(PatternType=2,Matrix=list(matrix),Shading=shading)))
    page.Contents=pdf.make_stream(b'/Pattern cs /P scn 0 0 400 200 re f')
    gradient=read_drawing(page).paths[0].state.fill
    vx,vy=160,70
    dx,dy=gradient.end[0]-gradient.start[0],gradient.end[1]-gradient.start[1]
    for x,y in ((10,20),(170,90),(80,5),(200,150)):
        target=point(matrix,x,y)
        expected=((x-10)*vx+(y-20)*vy)/(vx*vx+vy*vy)
        actual=((target[0]-gradient.start[0])*dx+(target[1]-gradient.start[1])*dy)/(dx*dx+dy*dy)
        assert actual==pytest.approx(expected)
    source=tmp_path/'affine.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'affine.ai',raster_fallback=False)['rasterized']


def test_rgb_gray_ramp_avoids_working_gray_interpolation():
    g=Gradient('gray',((0,Color('Gray',(0,))),(1,Color('Gray',(1,)))),(0,0),(100,0))
    item=PaintedPath([rectangle(0,0,100,100)],State(fill=g),'fill',False,1)
    _,private=make_private(Drawing((0,0,100,100),[item],[],{},color_model='RGB'),'test')
    # Both ramp colors are encoded as RGB, while the original drawing stays gray.
    assert b'0 0 0 0 1 1 1 2 1 6 50 100 %_BS' in private
    assert g.stops[0][1].model=='Gray'


def test_direct_fonts_in_nested_forms_do_not_share_an_objgen_cache(tmp_path):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(300,100));objects=pikepdf.Dictionary()
    for i,name in enumerate(('Helvetica','Courier')):
        form=pdf.make_stream(b'BT /F 20 Tf 1 0 0 1 0 0 Tm (ABC) Tj ET')
        form.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Form,BBox=[0,0,100,50],Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F=pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name('/'+name))))))
        objects[f'/Form{i}']=form
    page.Resources=pikepdf.Dictionary(XObject=objects)
    page.Contents=pdf.make_stream(b'q 1 0 0 1 20 20 cm /Form0 Do Q q 1 0 0 1 150 20 cm /Form1 Do Q')
    drawing=read_drawing(page)
    assert drawing.outlined_glyphs==6
    source=tmp_path/'fonts.pdf';pdf.save(source)
    result=convert(source,tmp_path/'fonts.ai',raster_fallback=False)
    assert result['outlined_glyphs']==6 and not result['rasterized']
    # Helvetica's B advance is ~13.34pt; Courier's is 12pt.
    a,b=drawing.paths[1],drawing.paths[4]
    assert a.paths[0].commands[0][1][0]-20 != pytest.approx(b.paths[0].commands[0][1][0]-150)


@pytest.mark.parametrize('decode,expected',[([1,0],b'\xff\x80\x00'),([.25,.75],b'\x40\x7f\xbf')])
def test_soft_mask_linear_decode_preserved_without_mutating_pdf(tmp_path,decode,expected):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    mask=pdf.make_stream(b'\x00\x7f\xff')
    mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=3,Height=1,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray,Decode=decode))
    image=pdf.make_stream(b'\xff\x00\x00'*3)
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=3,Height=1,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceRGB,SMask=mask))
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image));page.Contents=pdf.make_stream(b'q 80 0 0 40 10 20 cm /Im Do Q')
    assert read_drawing(page).images[0].alpha==expected
    assert list(mask.Decode)==decode and image.SMask.objgen==mask.objgen
    source=tmp_path/'mask.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'mask.ai',raster_fallback=False)['rasterized']


def test_interior_focus_radial_is_editable_and_moves_with_its_artboard(tmp_path):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(400,240))
    fn=pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0,0,1],C1=[1,0,0],N=1)
    sh=pikepdf.Dictionary(ShadingType=3,ColorSpace=pikepdf.Name.DeviceRGB,Coords=[175,120,0,200,100,75],Extend=[True,True],Function=fn)
    page.Resources=pikepdf.Dictionary(Shading=pikepdf.Dictionary(S=sh));page.Contents=pdf.make_stream(b'q 30 30 320 130 re W n /S sh Q')
    drawing=read_drawing(page);gradient=drawing.paths[0].state.fill
    assert gradient.start==(200,100) and gradient.end==(275,100) and gradient.focus==(175,120)
    shifted=translate_drawing(drawing,(-400,-240,0,0),2)
    assert shifted.paths[0].state.fill.focus==(-225,-120)
    source=tmp_path/'focus.pdf';pdf.save(source)
    report=convert(source,tmp_path/'focus.ai',raster_fallback=False)
    assert report['gradients']==1 and not report['rasterized']
    with pikepdf.open(tmp_path/'focus.ai') as ai:
        assert b'0 0 141.34019175 0.42687495 Bh' in read_private(ai)


@pytest.mark.parametrize('coords',[[100,100,1,100,100,75],[0,100,0,100,100,75]])
def test_unsupported_radial_geometry_does_not_publish(tmp_path,coords):
    from pdf2ai.vector import ConversionError
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(400,240))
    fn=pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0,0,1],C1=[1,0,0],N=1)
    sh=pikepdf.Dictionary(ShadingType=3,ColorSpace=pikepdf.Name.DeviceRGB,Coords=coords,Extend=[True,True],Function=fn)
    page.Resources=pikepdf.Dictionary(Shading=pikepdf.Dictionary(S=sh));page.Contents=pdf.make_stream(b'/S sh')
    with pytest.raises(ConversionError):
        read_drawing(page)
    source=tmp_path/'unsupported.pdf';output=tmp_path/'previous.ai'
    pdf.save(source);output.write_bytes(b'previous')
    with pytest.raises(ConversionError):
        convert(source,output,overwrite=True,raster_fallback=False)
    assert output.read_bytes()==b'previous'
