"""PDF fixtures for paths, transparency, forms and text."""
from pathlib import Path
import shutil
import pikepdf
import pymupdf
import pytest
from pdf2ai.native import convert, read_private
from pdf2ai.vector import read_drawing, ConversionError, BLEND_MODES, Gradient


def feature_pdf(path):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(600,600))
    page.obj.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
    function=pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[1,1,1],C1=[1,0,0],N=1)
    radial=pikepdf.Dictionary(ShadingType=3,ColorSpace=pikepdf.Name.DeviceRGB,
                             Coords=[100,460,0,100,460,70],Extend=[True,True],Function=function)
    # The nested form has its own resource named Alpha, shadowing the page's.
    inner=pdf.make_stream(b'/Alpha gs 0 0 1 rg -20 -20 100 100 re f')
    inner.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject,Subtype=pikepdf.Name.Form,
                                  BBox=[0,0,60,60],Matrix=[1,0,0,1,5,5],
                                  Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(Alpha=pikepdf.Dictionary(ca=0.5)))))
    outer=pdf.make_stream(b'q 1 0 0 1 10 10 cm /Child Do Q 1 0 0 rg 0 0 10 10 re f')
    outer.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject,Subtype=pikepdf.Name.Form,
                                  BBox=[0,0,80,80],Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Child=inner))))
    gs=pikepdf.Dictionary(Alpha=pikepdf.Dictionary(ca=0.2),Split=pikepdf.Dictionary(ca=0.5,CA=1,LW=4))
    content=['q 20 380 160 160 re W n /Radial sh Q',
             'q 230 400 120 120 re 260 430 60 60 re W* n 0 1 0 rg 210 380 160 160 re f Q',
             'q 1 0 0 1 410 410 cm /Form Do Q',
             'q /Split gs 1 0 0 rg 0 0 1 RG 420 320 80 50 re B Q']
    for i,mode in enumerate(BLEND_MODES):
        x=20+(i%5)*110;y=280-(i//5)*80
        gs[f'/{mode}']=pikepdf.Dictionary(BM=pikepdf.Name('/'+mode))
        content.append(f'q 0.2 0.6 0.8 rg {x} {y} 80 50 re f /{mode} gs 0.9 0.3 0.1 rg {x+20} {y+10} 80 50 re f Q')
    page.obj.Resources=pikepdf.Dictionary(Shading=pikepdf.Dictionary(Radial=radial),XObject=pikepdf.Dictionary(Form=outer),ExtGState=gs)
    page.obj.Contents=pdf.make_stream('\n'.join(content).encode());pdf.save(path)


def preview_equal(source,output):
    with pymupdf.open(source) as a,pymupdf.open(output) as b:
        assert a[0].get_pixmap().samples == b[0].get_pixmap().samples


def test_forms_clipping_radial_and_blends(tmp_path):
    source=tmp_path/'common.pdf';out=tmp_path/'common.ai';feature_pdf(source)
    result=convert(source,out)
    assert result['gradients']==1
    with pikepdf.open(source) as pdf:
        drawing=read_drawing(pdf.pages[0])
        assert drawing.paths[0].state.fill.radial
        assert len(drawing.paths[1].state.clips[0].paths)==2
        assert drawing.paths[2].state.fill_alpha==0.5
        assert drawing.paths[3].state.fill_alpha==1
        assert drawing.paths[2].paths[0].commands[0][1]==(405,405)
        assert len(drawing.paths[2].state.clips)==2
        assert drawing.paths[4].paint=='fill' and drawing.paths[5].paint=='stroke'
        assert {p.state.blend_mode for p in drawing.paths}==set(BLEND_MODES)
    from pdf2ai.native import native_items
    with pikepdf.open(source) as pdf:
        generated=list(native_items(read_drawing(pdf.pages[0])))
        radial_item=next(p for p in generated if isinstance(p.state.fill,Gradient) and p.state.fill.radial)
        assert radial_item.paths[0].commands[0][1]==(30,390)
        assert radial_item.paths[0].commands[2][1]==(170,530)
    preview_equal(source,out)


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_page_rotation_and_units(tmp_path,rotation):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,100))
    page.obj.Rotate=rotation;page.obj.UserUnit=2
    page.obj.Contents=pdf.make_stream(b'1 0 0 rg 20 10 40 30 re f')
    source=tmp_path/'rotate.pdf';out=tmp_path/'rotate.ai';pdf.save(source)
    result=convert(source,out)
    assert result['page_box']==([0,0,400,200] if rotation in (0,180) else [0,0,200,400])
    preview_equal(source,out)


def test_recursive_form_rejected(tmp_path):
    pdf=pikepdf.new();page=pdf.add_blank_page();form=pdf.make_stream(b'/Self Do')
    form.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Form,BBox=[0,0,10,10]))
    form.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Self=form))
    page.obj.Resources=form.Resources;page.obj.Contents=pdf.make_stream(b'/Self Do')
    source=tmp_path/'recursive.pdf';out=tmp_path/'recursive.ai';pdf.save(source)
    with pytest.raises(ConversionError,match='Recursive'):convert(source,out,raster_fallback=False)
    assert not out.exists()


@pytest.mark.parametrize('kind',['indexed','gray1','hard','key'])
def test_image_formats_and_masks(tmp_path,kind):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    image=pdf.make_stream(b'\x00\x01' if kind=='indexed' else b'\x80' if kind=='gray1' else b'\xff\x00\x00\x00\x00\xff')
    space=pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name.DeviceRGB,1,pikepdf.String(b'\xff\x00\x00\x00\x00\xff')]) if kind=='indexed' else pikepdf.Name.DeviceGray if kind=='gray1' else pikepdf.Name.DeviceRGB
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=2,Height=1,BitsPerComponent=1 if kind=='gray1' else 8,ColorSpace=space))
    if kind=='hard':
        mask=pdf.make_stream(b'\x40');mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,ImageMask=True,Width=2,Height=1,BitsPerComponent=1));image.Mask=mask
    if kind=='key':image.Mask=[255,255,0,0,0,0]
    page.obj.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image))
    page.obj.Contents=pdf.make_stream(b'q 80 0 0 40 10 10 cm /Im Do Q')
    source=tmp_path/'image.pdf';out=tmp_path/'image.ai';pdf.save(source)
    convert(source,out)
    with pikepdf.open(source) as p:
        raster=read_drawing(p.pages[0]).images[0]
        if kind in ('hard','key'):assert raster.alpha==(b'\xff\x00' if kind=='hard' else b'\x00\xff')
        if kind=='indexed':assert raster.pixels==b'\xff\x00\x00\x00\x00\xff'
        if kind=='gray1':assert raster.pixels==b'\xff\x00'
    preview_equal(source,out)


def test_outlined_text(tmp_path):
    if not any(shutil.which(n) for n in ('gs','gswin64c','gswin32c')):pytest.skip('Optional Ghostscript not installed')
    source=tmp_path/'text.pdf';out=tmp_path/'text.ai'
    with pymupdf.open() as pdf:
        page=pdf.new_page(width=300,height=200);page.insert_text((20,70),'PDF to AI: outlines!',fontsize=16);pdf.save(source)
    result=convert(source,out,outline_text=True)
    assert result['text_outlined'] and result['painted_paths']>10
    preview_equal(source,out)
    with pikepdf.open(out) as pdf:assert b' BT' not in read_private(pdf)
