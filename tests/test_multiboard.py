"""Multi-artboard geometry, layer/color identity and atomic failure behavior."""
import pikepdf
import pytest

from pdf2ai.layers import Layer
from pdf2ai.multiboard import convert_document, translate_drawing
from pdf2ai.native import make_private
from pdf2ai.vector import (Clip, Color, ConversionError, Drawing, Gradient,
                          PaintedPath, Raster, State, Subpath)


def test_translation_moves_paths_clips_gradients_and_images_without_scaling():
    layer=Layer((10,0),'背景',False,True,False)
    p=Subpath([('m',(10,20)),('c',(20,30,40,50,60,70))],False)
    g=Gradient('Gradient 1',((0,Color('RGB',(0,0,0))),(1,Color('RGB',(1,1,1)))),(10,20),(50,60))
    state=State(fill=g,layer=layer,clips=(Clip([p],False),),matrix=(100,0,0,200,10,20))
    painted=PaintedPath([p],state,'fill',False,1)
    image=Raster(1,1,'RGB',b'\x00\x00\x00',None,state)
    drawing=Drawing((10,20,110,220),[painted],[],{},images=[image],items=[painted,image],layers=[layer])
    shifted=translate_drawing(drawing,(-200,-100,-100,100),4)
    assert shifted.paths[0].paths[0].commands==[('m',(-200,-100)),('c',(-190,-90,-170,-70,-150,-50))]
    assert shifted.paths[0].state.fill.start==(-200,-100)
    assert shifted.paths[0].state.fill.end==(-160,-60)
    assert shifted.images[0].state.matrix==(100,0,0,200,-200,-100)
    assert shifted.paths[0].state.clips[1].paths[0].commands[0]==('m',(-200,-100))
    assert shifted.layers[0].name=='ページ 4 / 背景'
    assert not shifted.layers[0].visible and shifted.layers[0].locked and not shifted.layers[0].printable
    assert drawing.paths[0].paths[0].commands[0]==('m',(10,20))
    _,private=make_private(shifted,'test',artboards=[('Page 4',shifted.box)])
    assert b'%_(Page 4) /UnicodeString (Name)' in private


def test_canvas_overflow_is_rejected_before_overwrite(tmp_path):
    source=tmp_path/'large.pdf';output=tmp_path/'large.ai'
    pdf=pikepdf.new()
    for _ in range(2):pdf.add_blank_page(page_size=(14000,14000))
    pdf.save(source);output.write_bytes(b'previous AI')
    with pytest.raises(ConversionError,match='キャンバス'):
        convert_document(source,output,overwrite=True)
    assert output.read_bytes()==b'previous AI'


def test_conflicting_spot_definitions_prevent_combined_output(tmp_path):
    pdf=pikepdf.new()
    for cmyk in ([1,0,0,0],[0,1,0,0]):
        page=pdf.add_blank_page(page_size=(100,100))
        fn=pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0]*4,C1=cmyk,N=1)
        page.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(S=pikepdf.Array([
            pikepdf.Name.Separation,pikepdf.Name('/Same Spot'),pikepdf.Name.DeviceCMYK,fn])))
        page.Contents=pdf.make_stream(b'/S cs 1 scn 10 10 20 20 re f')
    source=tmp_path/'spots.pdf';output=tmp_path/'spots.ai';pdf.save(source)
    with pytest.raises(ConversionError,match='特色'):
        convert_document(source,output)
    assert not output.exists()
