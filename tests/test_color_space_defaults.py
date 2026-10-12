"""Changing cs/CS resets the current color, even without sc/SC."""
import pikepdf
import pytest
from pdf2ai.vector import read_drawing,ConversionError


def page_with(content):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    spot=pikepdf.Array([pikepdf.Name.Separation,pikepdf.Name('/Custom'),pikepdf.Name.DeviceCMYK,
        pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0]*4,C1=[1,0,0,0],N=1)])
    page.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(
        Spot=spot,Alias=pikepdf.Name.DeviceGray))
    page.Contents=pdf.make_stream(content)
    return pdf,page


@pytest.mark.parametrize('stroke',[False,True])
@pytest.mark.parametrize('space,model,values',[
    ('DeviceGray','Gray',(0,)),('DeviceRGB','RGB',(0,0,0)),
    ('DeviceCMYK','CMYK',(0,0,0,1)),('Spot','Spot',(1,)),('Alias','Gray',(0,)),
])
def test_color_space_switch_resets_selected_color(stroke,space,model,values):
    content=(b'1 0 0 '+(b'RG' if stroke else b'rg')+b' /'+space.encode()+
        (b' CS 2 w 10 10 80 80 re S' if stroke else b' cs 10 10 80 80 re f'))
    pdf,page=page_with(content)
    state=read_drawing(page).paths[0].state
    color=state.stroke if stroke else state.fill
    assert color.model==model and color.values==values


def test_graphics_restore_restores_color_from_before_switch():
    pdf,page=page_with(b'1 0 0 rg q /DeviceGray cs 10 10 20 20 re f Q 40 40 20 20 re f')
    paths=read_drawing(page).paths
    assert paths[0].state.fill.model=='Gray'
    assert paths[1].state.fill.model=='RGB' and paths[1].state.fill.values==(1,0,0)


def test_pattern_switch_cannot_reuse_a_previous_solid_color():
    pdf,page=page_with(b'1 0 0 rg /Pattern cs 10 10 80 80 re f')
    with pytest.raises(ConversionError,match='Pattern'):
        read_drawing(page)


def test_icc_color_space_switch_uses_zero_components():
    from PIL import ImageCms
    pdf,page=page_with(b'1 0 0 rg /Profile cs 10 10 80 80 re f')
    profile=pdf.make_stream(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    profile.N=3
    page.Resources.ColorSpace.Profile=pikepdf.Array([pikepdf.Name.ICCBased,profile])
    color=read_drawing(page).paths[0].state.fill
    assert color.model=='RGB' and color.values==(0,0,0)
    assert color.icc_values==(0,0,0)
