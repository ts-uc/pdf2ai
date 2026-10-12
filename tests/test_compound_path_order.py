"""Native compound fills keep PDF order without changing their anchors or winding."""
import pytest

from pdf2ai.native import make_private, num
from pdf2ai.vector import Color, Drawing, PaintedPath, State, Subpath


def rectangle(x,y,w,h):
    return Subpath([('m',(x,y)),('L',(x+w,y)),('L',(x+w,y+h)),('L',(x,y+h))],True)


@pytest.mark.parametrize('evenodd',[False,True])
def test_opaque_compound_fill_order_is_reversed_but_geometry_is_unchanged(evenodd):
    outer=rectangle(1.23456789,2.34567891,70,80)
    inner=rectangle(10.12345678,20.23456789,15,25)
    # Opposite winding is significant for a nonzero-winding hole.
    inner.commands=[inner.commands[0],*reversed(inner.commands[1:])]
    item=PaintedPath([outer,inner],State(fill=Color('CMYK',(0,0,0,1))),'fill',evenodd,1)
    drawing=Drawing((0,0,100,100),[item],[],{})
    snapshots=[list(path.commands) for path in item.paths]
    _,private=make_private(drawing,'test')
    assert private.index(b'10.12345678 20.23456789 m')<private.index(b'1.23456789 2.34567891 m')
    assert [path.commands for path in item.paths]==snapshots
    assert item.paths==[outer,inner]
    for op,coords in snapshots[0]+snapshots[1]:
        assert (' '.join(num(v) for v in coords)+' '+op).encode() in private
    assert (f'{int(evenodd)} XR').encode() in private


@pytest.mark.parametrize('paint,alpha,blend',[
    ('stroke',1,'Normal'),('both',1,'Normal'),('fill',.5,'Normal'),('fill',1,'Multiply'),
])
def test_nonopaque_or_stroked_compounds_keep_original_order(paint,alpha,blend):
    item=PaintedPath([rectangle(1,2,70,80),rectangle(10,20,15,25)],
                     State(fill=Color('CMYK',(0,0,0,1)),fill_alpha=alpha,blend_mode=blend),
                     paint,False,1)
    _,private=make_private(Drawing((0,0,100,100),[item],[],{}),'test')
    assert private.index(b'1 2 m')<private.index(b'10 20 m')
