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


@pytest.mark.parametrize('model,matte,preblended,expected',[
    ('RGB',[1,1,1],bytes([255,127,127,255,255,255,255,0,0]),bytes([255,0,0,0,0,0,255,0,0])),
    ('CMYK',[0,0,0,0],bytes([128,0,0,0,0,0,0,0,255,0,0,0]),bytes([255,0,0,0,0,0,0,0,255,0,0,0])),
    ('Gray',[1],bytes([127,255,0]),bytes([0,0,0])),
])
def test_soft_mask_matte_recovers_straight_channels(tmp_path,model,matte,preblended,expected):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    mask=pdf.make_stream(bytes([128,0,255]));mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=3,Height=1,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray,Matte=matte))
    image=pdf.make_stream(preblended);image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=3,Height=1,BitsPerComponent=8,ColorSpace=pikepdf.Name('/Device'+model),SMask=mask))
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image));page.Contents=pdf.make_stream(b'q 80 0 0 40 10 20 cm /Im Do Q')
    raster=read_drawing(page).images[0]
    assert raster.pixels==expected and raster.alpha==bytes([128,0,255])
    assert list(mask.Matte)==matte and image.SMask.objgen==mask.objgen
    source=tmp_path/'matte.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'matte.ai',raster_fallback=False)['rasterized']


@pytest.mark.parametrize('bits,raw,expected',[
    (1,b'\x60',bytes([0,255,255,0])),
    (2,b'\x1b',bytes([0,85,170,255])),
    (4,b'\x05\xaf',bytes([0,85,170,255])),
    (16,b'\x00\x00\x55\x55\xaa\xaa\xff\xff',bytes([0,85,170,255])),
])
def test_soft_mask_bit_depths(tmp_path,bits,raw,expected):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    mask=pdf.make_stream(raw);mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=4,Height=1,BitsPerComponent=bits,ColorSpace=pikepdf.Name.DeviceGray,Decode=[1,0]))
    image=pdf.make_stream(b'\xff\x00\x00'*4);image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=4,Height=1,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceRGB,SMask=mask))
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image));page.Contents=pdf.make_stream(b'q 80 0 0 40 10 20 cm /Im Do Q')
    assert read_drawing(page).images[0].alpha==bytes(255-v for v in expected)
    assert list(mask.Decode)==[1,0]
    source=tmp_path/'depth.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'depth.ai',raster_fallback=False)['rasterized']


@pytest.mark.parametrize('matte',[[1,1],[-1,0,0],['invalid',0,0]])
def test_invalid_matte_does_not_mutate_mask(matte):
    from pdf2ai.vector import ConversionError
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    mask=pdf.make_stream(b'\x80');mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=1,Height=1,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray,Matte=matte))
    image=pdf.make_stream(b'\xff\x80\x80');image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=1,Height=1,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceRGB,SMask=mask))
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image));page.Contents=pdf.make_stream(b'/Im Do')
    with pytest.raises(ConversionError):
        read_drawing(page)
    assert image.SMask.objgen==mask.objgen


@pytest.mark.parametrize('matrix',[(2,0,0,.5,20,20),(1,.3,.6,1,30,15),(-2,0,0,.5,250,20)])
@pytest.mark.parametrize('cap',[0,1,2])
def test_nonuniform_straight_strokes_preserve_edges_and_state(tmp_path,matrix,cap):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(300,150))
    page.Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(CA=.4,ca=.9)))
    content='q '+ ' '.join(map(str,matrix))+f' cm /A gs 0.2 0.4 0.8 RG 12 w {cap} J 10 20 m 90 60 l S Q'
    page.Contents=pdf.make_stream(content.encode())
    drawing=read_drawing(page);item=drawing.paths[0]
    assert drawing.outlined_strokes==1
    assert item.paint=='fill' and item.state.fill.values==pytest.approx((.2,.4,.8))
    assert item.state.fill_alpha==.4
    # The exact quadrilateral is the transformed user-space stroke envelope.
    import math
    tx,ty=80/math.hypot(80,40),40/math.hypot(80,40)
    extra=6 if cap==2 else 0
    expected=[point(matrix,10-extra*tx-6*ty,20-extra*ty+6*tx),
              point(matrix,90+extra*tx-6*ty,60+extra*ty+6*tx),
              point(matrix,90+extra*tx+6*ty,60+extra*ty-6*tx),
              point(matrix,10-extra*tx+6*ty,20-extra*ty-6*tx)]
    for (_,actual),target in zip(item.paths[0].commands,expected):assert actual==pytest.approx(target)
    assert len(item.paths)==(3 if cap==1 else 1)
    source=tmp_path/'stroke.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'stroke.ai',raster_fallback=False)['rasterized']


@pytest.mark.parametrize('path',['0 0 m 30 0 l h S','[0 3] 0 d 0 0 m 30 0 l S','0 0 m 30 0 30 30 0 30 c S'])
def test_complex_nonuniform_strokes_still_rejected(path):
    from pdf2ai.vector import ConversionError
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Contents=pdf.make_stream(('2 0 0 1 0 0 cm '+path).encode())
    with pytest.raises(ConversionError):read_drawing(page)


@pytest.mark.parametrize('dash,phase,intervals',[
    ((3,),1,[(0,2),(5,8),(11,12)]),
    ((3,2),4,[(1,4),(6,9),(11,12)]),
    ((3,2),14,[(1,4),(6,9),(11,12)]),
    ((2,3,4),0,[(0,2),(5,9),(11,12)]),
])
def test_affine_dash_intervals_and_phase_reset(dash,phase,intervals,tmp_path):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    content=f'2 0.5 0.6 1 10 10 cm 2 w [{' '.join(map(str,dash))}] {phase} d 0 0 m 12 0 l 0 10 m 12 10 l S'
    page.Contents=pdf.make_stream(content.encode());drawing=read_drawing(page)
    item=drawing.paths[0];assert item.paint=='fill' and drawing.outlined_strokes==2
    assert len(item.paths)==len(intervals)*2
    matrix=(2,.5,.6,1,10,10)
    for row,y in enumerate((0,10)):
        for i,(start,end) in enumerate(intervals):
            actual=item.paths[row*len(intervals)+i].commands
            expected=[point(matrix,start,y+1),point(matrix,end,y+1),point(matrix,end,y-1),point(matrix,start,y-1)]
            for (_,coords),p in zip(actual,expected):assert coords==pytest.approx(p)
    source=tmp_path/'dash.pdf';pdf.save(source)
    report=convert(source,tmp_path/'dash.ai',raster_fallback=False)
    assert not report['rasterized'] and report['outlined_strokes']==2


def test_dash_gap_only_preserves_pending_clip():
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Contents=pdf.make_stream(b'2 0 0 1 0 0 cm [1 100] 2 d 0 0 m 10 0 l W S 1 0 0 rg 0 0 20 20 re f')
    drawing=read_drawing(page)
    assert len(drawing.paths)==1 and len(drawing.paths[0].state.clips)==1
    assert drawing.outlined_strokes==1


def test_excessively_dense_dashes_are_rejected_without_publishing(tmp_path):
    from pdf2ai.vector import ConversionError
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Contents=pdf.make_stream(b'2 0 0 1 0 0 cm [.0001 .0001] 0 d 0 0 m 100 0 l S')
    source=tmp_path/'dense.pdf';pdf.save(source);target=tmp_path/'existing.ai';target.write_bytes(b'original')
    with pytest.raises(ConversionError,match='complexity'):
        convert(source,target,overwrite=True,raster_fallback=False)
    assert target.read_bytes()==b'original'


@pytest.mark.parametrize('matrix',[(2,0,0,.5,20,20),(1,.3,.6,1,30,15),(-2,0,0,.5,250,20)])
@pytest.mark.parametrize('size,line_width',[( (60,30),8),((-60,30),8),((60,-30),8),((60,30),40)])
def test_nonuniform_rectangle_frame_has_exact_ring(tmp_path,matrix,size,line_width):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(300,150));w,h=size
    page.Contents=pdf.make_stream((' '.join(map(str,matrix))+f' cm {line_width} w 10 20 {w} {h} re S').encode())
    drawing=read_drawing(page);item=drawing.paths[0]
    assert item.paint=='fill' and drawing.outlined_strokes==1
    r=line_width/2;x0,x1=sorted((10,10+w));y0,y1=sorted((20,20+h))
    outer=[point(matrix,x,y) for x,y in ((x0-r,y0-r),(x1+r,y0-r),(x1+r,y1+r),(x0-r,y1+r))]
    assert len(item.paths)==(2 if min(abs(w),abs(h))>line_width else 1)
    actual=[p for _,p in item.paths[0].commands]
    for target in outer: assert any(p==pytest.approx(target) for p in actual)
    def area(path):
        p=[v for _,v in path.commands]
        return sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(p,p[1:]+p[:1]))/2
    det=matrix[0]*matrix[3]-matrix[1]*matrix[2]
    assert area(item.paths[0])*det<0
    if len(item.paths)==2:
        assert area(item.paths[1])*det>0
        assert abs(sum(map(area,item.paths)))==pytest.approx(abs(det)*2*line_width*(abs(w)+abs(h)))
    source=tmp_path/'frame.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'frame.ai',raster_fallback=False)['rasterized']


@pytest.mark.parametrize('style',['[3 2] 0 d'])
def test_nonuniform_dashed_rectangle_is_supported(style):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Contents=pdf.make_stream(f'2 0 0 1 0 0 cm {style} 10 10 40 30 re S'.encode())
    assert read_drawing(page).outlined_strokes==1


def test_nonuniform_rectangle_fill_and_stroke_keep_distinct_colors():
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,100))
    page.Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(CA=1,ca=1)))
    page.Contents=pdf.make_stream(b'2 0 0 1 0 0 cm /A gs 1 0 0 rg 0 0 1 RG 6 w 10 10 60 30 re B')
    drawing=read_drawing(page)
    fill,stroke=drawing.paths
    assert fill.paint==stroke.paint=='fill'
    assert fill.state.fill.values==(1,0,0) and fill.state.fill_alpha==1
    assert stroke.state.fill.values==(0,0,1) and stroke.state.fill_alpha==1
    assert len(fill.paths)==1 and len(stroke.paths)==2


@pytest.mark.parametrize('transform',['2 0 0 1 0 0 cm',''])
def test_split_transparent_fill_stroke_falls_back_and_strict_is_atomic(tmp_path,transform):
    from pdf2ai.vector import ConversionError
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,100))
    page.Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(CA=.4,ca=.8)))
    page.Contents=pdf.make_stream((transform+' /A gs 1 0 0 rg 0 0 1 RG 6 w 10 10 60 30 re B').encode())
    source=tmp_path/'transparent.pdf';pdf.save(source);target=tmp_path/'existing.ai';target.write_bytes(b'original')
    with pytest.raises(ConversionError,match='knockout'):
        convert(source,target,overwrite=True,raster_fallback=False)
    assert target.read_bytes()==b'original'
    result=convert(source,tmp_path/'fallback.ai')
    assert result['rasterized'] and 'knockout' in result['fallback_reason']


def test_transparent_text_fill_stroke_split_is_rejected():
    from pdf2ai.vector import ConversionError
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,100))
    page.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F=pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica)),ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(CA=.4,ca=.8)))
    page.Contents=pdf.make_stream(b'/A gs BT /F 30 Tf 2 Tr 1 0 0 1 20 20 Tm (ABC) Tj ET')
    with pytest.raises(ConversionError,match='knockout'):read_drawing(page)


@pytest.mark.parametrize('dash,phase,centers',[
    ((0,5),0,[0,5,10]),((0,5),2,[3,8]),((0,5),12,[3,8]),
    ((0,3,0,2),0,[0,3,5,8,10]),
])
def test_round_dotted_strokes_include_zero_length_dashes(tmp_path,dash,phase,centers):
    from pdf2ai.vector import outline_straight_strokes
    matrix=(2,.3,.6,1,10,20);state=State(matrix=matrix,width=2,cap=1,dash=dash,phase=phase)
    path=Subpath([('m',point(matrix,0,0)),('L',point(matrix,10,0))])
    shapes=outline_straight_strokes([path],state)
    assert len(shapes)==len(centers)
    for shape,x in zip(shapes,centers):
        assert len(shape.commands)==5 and shape.commands[0][1]==pytest.approx(point(matrix,x,1))
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Contents=pdf.make_stream((' '.join(map(str,matrix))+f' cm 2 w 1 J [{' '.join(map(str,dash))}] {phase} d 0 0 m 10 0 l S').encode())
    source=tmp_path/'dots.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'dots.ai',raster_fallback=False)['rasterized']


@pytest.mark.parametrize('join,count',[(0,3),(1,3),(2,3)])
@pytest.mark.parametrize('matrix',[(2,0,0,.5,20,20),(1,.3,.6,1,30,15),(-2,0,0,.5,250,20)])
def test_nonuniform_polyline_join_regions(matrix,join,count,tmp_path):
    from pdf2ai.vector import outline_straight_strokes
    state=State(matrix=matrix,width=4,join=join)
    path=Subpath([('m',point(matrix,10,10)),('L',point(matrix,50,10)),('L',point(matrix,50,50))])
    contours=outline_straight_strokes([path],state)
    assert len(contours)==count
    join_shape=contours[-1]
    if join==0:
        assert any(coords==pytest.approx(point(matrix,52,8)) for _,coords in join_shape.commands)
    elif join==1:
        assert len(join_shape.commands)==5 and join_shape.commands[0][1]==pytest.approx(point(matrix,50,12))
    else:
        assert len(join_shape.commands)==3
        for x,y in ((50,10),(50,8),(52,10)):
            assert any(coords==pytest.approx(point(matrix,x,y)) for _,coords in join_shape.commands)
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(300,150))
    page.Contents=pdf.make_stream((' '.join(map(str,matrix))+f' cm 4 w {join} j 10 10 m 50 10 l 50 50 l S').encode())
    source=tmp_path/'polyline.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'polyline.ai',raster_fallback=False)['rasterized']


def test_miter_limit_bevels_sharp_turn_and_closed_polygon_accepts_explicit_closure():
    from pdf2ai.vector import outline_straight_strokes
    matrix=(2,0,0,1,0,0);state=State(matrix=matrix,width=4,miter=1)
    path=Subpath([('m',(0,0)),('L',(80,0)),('L',(80,40))])
    shapes=outline_straight_strokes([path],state)
    assert len(shapes[-1].commands)==3
    vertices=[(0,0),(80,0),(60,40),(0,0)]
    closed=Subpath([('m' if i==0 else 'L',v) for i,v in enumerate(vertices)],True)
    assert len(outline_straight_strokes([closed],state))==6


@pytest.mark.parametrize('join',[0,1,2])
def test_rectangle_corner_styles_preserve_transparency(join,tmp_path):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,150))
    page.Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(CA=.4)))
    page.Contents=pdf.make_stream(f'1.5 .2 .5 .7 20 20 cm /A gs 8 w {join} j 20 20 60 40 re S'.encode())
    drawing=read_drawing(page)
    assert drawing.paths[0].state.fill_alpha==.4 and drawing.outlined_strokes==1
    source=tmp_path/'join.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'join.ai',raster_fallback=False)['rasterized']


@pytest.mark.parametrize('closed',[False,True])
@pytest.mark.parametrize('cap',[0,1,2])
@pytest.mark.parametrize('join',[0,1,2])
def test_dash_crosses_corners_without_restarting_phase(tmp_path,closed,cap,join):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,100))
    close='h' if closed else ''
    page.Contents=pdf.make_stream(f'2 .3 .6 1 10 10 cm 4 w {cap} J {join} j [14 8] 0 d 0 0 m 10 0 l 10 10 l 20 10 l {close} S'.encode())
    drawing=read_drawing(page);assert drawing.outlined_strokes==1
    contours=drawing.paths[0].paths
    # The first 14-unit dash must retain the corner at (10,0), so it has
    # two segment bands and a join; a segment-by-segment reset loses this join.
    assert len(contours)>=3
    source=tmp_path/'corner.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'corner.ai',raster_fallback=False)['rasterized']


def test_dashed_closed_frame_entirely_on_has_no_endpoint_caps():
    from pdf2ai.vector import outline_straight_strokes
    matrix=(2,0,0,1,0,0);state=State(matrix=matrix,width=2,cap=1,dash=(1000,10))
    path=Subpath([('m',(0,0)),('L',(20,0)),('L',(20,10)),('L',(0,10))],True)
    shapes=outline_straight_strokes([path],state)
    # Four bands and four miter joins, with no round endpoint circles.
    assert len(shapes)==8 and all(len(p.commands)==4 for p in shapes)


def test_dotted_closed_polygon_keeps_input_dash_state():
    from pdf2ai.vector import outline_straight_strokes
    matrix=(2,0,0,1,0,0);state=State(matrix=matrix,width=2,cap=1,dash=(0,5),phase=2)
    path=Subpath([('m',(0,0)),('L',(20,0)),('L',(20,10)),('L',(0,10))],True)
    shapes=outline_straight_strokes([path],state)
    assert len(shapes)==8 and all(len(p.commands)==5 for p in shapes)
    assert state.dash==(0,5) and state.phase==2




@pytest.mark.parametrize('bits,raw,width,mask,expected',[
    (1,b'\x50',4,[1,1],b'\xff\0\xff\0'),
    (2,b'\x18',3,[1,2],b'\xff\0\0'),
    (4,b'\x01\x20',3,[1,2],b'\xff\0\0'),
    (8,b'\0\1\2',3,[1,2],b'\xff\0\0'),
])
def test_indexed_color_key_mask_uses_indices_and_row_padding(bits,raw,width,mask,expected,tmp_path):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    # Palette entries 0 and 1 intentionally have the same RGB color. Transparency
    # must follow sample indices rather than comparing expanded RGB channels.
    palette=b'\xff\0\0\xff\0\0\0\0\xff'
    space=pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name.DeviceRGB,2,pikepdf.String(palette)])
    image=pdf.make_stream(raw*2);image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=width,Height=2,BitsPerComponent=bits,ColorSpace=space,Mask=mask))
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image));page.Contents=pdf.make_stream(b'q 80 0 0 40 10 20 cm /Im Do Q')
    raster=read_drawing(page).images[0]
    assert raster.alpha==expected*2 and list(image.Mask)==mask
    source=tmp_path/'indexed.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'indexed.ai',raster_fallback=False)['rasterized']


@pytest.mark.parametrize('mask',[[-1,1],[2,1],[0,4],[0,1,2],[.5,1],['invalid',1]])
def test_invalid_indexed_color_key_is_rejected_without_mutating_image(mask):
    from pdf2ai.vector import ConversionError
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    image=pdf.make_stream(b'\x00');image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=1,Height=1,BitsPerComponent=2,ColorSpace=pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name.DeviceRGB,1,pikepdf.String(b'\xff\0\0\0\0\xff')]),Mask=mask))
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image));page.Contents=pdf.make_stream(b'/Im Do')
    with pytest.raises(ConversionError):read_drawing(page)
    assert list(image.Mask)==mask
