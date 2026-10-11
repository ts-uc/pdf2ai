from pathlib import Path
import sys

import pikepdf
import pytest
from PIL import ImageCms

from pdf2ai.color_management import cmyk_to_rgb
from pdf2ai.native import convert, read_private
from pdf2ai.vector import read_drawing, GroupBoundary, ConversionError
from pdf2ai.multiboard import convert_document

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from make_color_transparency_cases import group_scene, icc_scene
from make_conversion_suite import image_scene


@pytest.mark.parametrize('isolated',[False,True])
@pytest.mark.parametrize('knockout',[False,True])
def test_group_opacity_is_applied_once_and_keeps_children_editable(tmp_path,isolated,knockout):
    pdf=group_scene(isolated)
    pdf.pages[0].Resources.XObject.Form.Group.K=knockout
    drawing=read_drawing(pdf.pages[0],root=pdf.Root)
    boundaries=[item for item in drawing.items if isinstance(item,GroupBoundary)]
    assert len(boundaries)==2 and boundaries[0].begin and not boundaries[1].begin
    assert boundaries[1].state.fill_alpha==.6
    assert boundaries[1].isolated==isolated and boundaries[1].knockout==knockout
    assert [p.state.fill_alpha for p in drawing.paths]==[1,1,.5]
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai';pdf.save(source)
    report=convert(source,output,raster_fallback=False)
    assert report['transparency_groups']==1 and not report['rasterized']
    with pikepdf.open(output) as result:
        private=read_private(result)
        assert f'0 0.6 {int(isolated)} {1 if knockout else 2} 0 Xy'.encode() in private


def test_nested_groups_survive_combination_without_becoming_images(tmp_path):
    pdf=group_scene(True,nested=True);source=tmp_path/'source.pdf';pdf.save(source)
    reports=convert_document(source,tmp_path/'output.ai',raster_fallback=False)
    assert reports[0]['transparency_groups']==2
    assert reports[0]['images']==0


@pytest.mark.parametrize('image',[False,True])
def test_icc_rgb_preserves_resources_and_is_supported_natively(tmp_path,image):
    profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    pdf=icc_scene(profile,3,image)
    original_profile=pdf.pages[0].Resources.XObject.Im.ColorSpace[1] if image else pdf.pages[0].Resources.ColorSpace.Profile[1]
    drawing=read_drawing(pdf.pages[0],root=pdf.Root)
    assert original_profile.read_bytes()==profile
    if image:
        assert drawing.images[0].model=='RGB'
        assert str(pdf.pages[0].Resources.XObject.Im.ColorSpace[0])=='/ICCBased'
    else: assert drawing.paths[0].state.fill.model=='RGB'
    source=tmp_path/'source.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'output.ai',raster_fallback=False)['rasterized']


def test_invalid_icc_fails_atomically(tmp_path):
    pdf=icc_scene(b'invalid profile',3)
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai';pdf.save(source);output.write_bytes(b'previous')
    with pytest.raises(ConversionError,match='ICC'):
        convert(source,output,overwrite=True,raster_fallback=False)
    assert output.read_bytes()==b'previous'


def test_mixed_rgb_cmyk_image_uses_explicit_renderer_conversion():
    pdf=image_scene('cmyk-soft-mask')
    pdf.pages[0].Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
    image=pdf.pages[0].Resources.XObject.Im
    expected=cmyk_to_rgb(image.read_bytes(),int(image.Width),int(image.Height))
    drawing=read_drawing(pdf.pages[0],root=pdf.Root)
    assert drawing.images[0].pixels==expected
    assert drawing.images[0].model=='RGB' and drawing.color_conversions
    assert str(image.ColorSpace)=='/DeviceCMYK'


@pytest.mark.parametrize('image',[False,True])
def test_default_rgb_profile_is_honored_without_mutating_input(image):
    profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    pdf=icc_scene(profile,3,image)
    page=pdf.pages[0]
    space=page.Resources.XObject.Im.ColorSpace if image else page.Resources.ColorSpace.Profile
    page.Resources.ColorSpace=pikepdf.Dictionary(DefaultRGB=space)
    if image:
        page.Resources.XObject.Im.ColorSpace=pikepdf.Name.DeviceRGB
    else:
        page.Contents=pdf.make_stream(b'0.2 0.5 0.8 rg 30 30 300 130 re f')
    drawing=read_drawing(page,root=pdf.Root)
    assert any('ICC' in item for item in drawing.color_conversions)
    if image:assert str(page.Resources.XObject.Im.ColorSpace)=='/DeviceRGB'


def test_intent_changed_after_setting_color_is_applied_at_paint(monkeypatch):
    profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    pdf=icc_scene(profile,3)
    page=pdf.pages[0]
    page.Contents=pdf.make_stream(b'/Profile cs 0.2 0.5 0.8 scn /Saturation ri 30 30 300 130 re f')
    def transform(pixels,width,height,model,profile,intent=1):
        return bytes([intent*50,20,30])
    monkeypatch.setattr('pdf2ai.color_management.icc_to_rgb',transform)
    drawing=read_drawing(page,root=pdf.Root)
    assert drawing.paths[0].state.fill.values==(100/255,20/255,30/255)


def test_invalid_icc_range_does_not_silently_change_colors():
    profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    pdf=icc_scene(profile,3)
    pdf.pages[0].Resources.ColorSpace.Profile[1].Range=[-1,1]*3
    with pytest.raises(ConversionError,match='Range'):
        read_drawing(pdf.pages[0],root=pdf.Root)
