"""Illustrator standard settings, exact fill bounds and safe PDF page defaults."""
import pikepdf
import pytest
import xml.etree.ElementTree as ET

from pdf2ai.native import convert, read_private, ps_string
from pdf2ai.document_defaults import fill_artwork_bounds
from pdf2ai.multiboard import convert_document
from pdf2ai.vector import read_drawing


def document(path, commands=b'/S cs 1 scn 10 20 30 40 re f', title=None):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,200))
    page.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceCMYK)
    page.ArtBox=[0,0,100,200]
    page.Rotate=0
    pdf.Root.PageLayout=pikepdf.Name.SinglePage
    pdf.Root.ViewerPreferences=pikepdf.Dictionary(Direction=pikepdf.Name.L2R)
    fn=pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0]*4,C1=[0,.16,.17,0],N=1)
    page.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(
        S=pikepdf.Array([pikepdf.Name.Separation,pikepdf.Name('/DIC 1s'),pikepdf.Name.DeviceCMYK,fn])))
    page.Contents=pdf.make_stream(commands)
    if title:
        pdf.docinfo['/Title']=title;pdf.docinfo['/Author']='Designer'
    pdf.save(path)


def test_standard_defaults_keep_artwork_and_supply_real_document_metadata(tmp_path):
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai';document(source)
    original=source.read_bytes()
    report=convert(source,output,raster_fallback=False)
    assert source.read_bytes()==original
    assert report['layers'][0]['name']=='レイヤー 1'
    with pikepdf.open(output) as pdf:
        page=pdf.pages[0];private=read_private(pdf)
        assert b'%AI5_RulerUnits: 2\r' in private
        assert (ps_string('アートボード 1')+' /UnicodeString (Name)').encode() in private
        assert b'%_1 /Bool (IsArtboardDefaultName)' in private
        assert (ps_string('[レジストレーション]')+' 0 Xs').encode() in private
        assert b'%%DocumentProcessColors:\r' in private
        assert b'%%HiResBoundingBox: 10 20 40 60\r' in private
        assert list(page.ArtBox)==[10,20,40,60]
        assert '/Group' not in page.obj
        assert '/Rotate' not in page.obj
        assert '/PageLayout' not in pdf.Root and '/ViewerPreferences' not in pdf.Root
        assert list(page.MediaBox)==[0,0,100,200]
        thumbnail=page.obj.Thumb
        assert thumbnail.Width==26 and thumbnail.Height==52
        assert len(thumbnail.read_bytes())==26*52*3
        assert str(pdf.docinfo['/Title'])=='output'
        xml=ET.fromstring(pdf.Root.Metadata.read_bytes())
        graphic='{http://ns.adobe.com/xap/1.0/g/}'
        assert xml.find('.//'+graphic+'swatchName').text=='DIC 1s'
        assert xml.find('.//'+graphic+'mode').text=='CMYK'
        assert float(xml.find('.//'+graphic+'magenta').text)==16
        assert float(xml.find('.//'+graphic+'yellow').text)==17
        assert xml.find('.//{http://ns.adobe.com/xap/1.0/g/img/}format').text=='JPEG'
        assert '/LastModified' in page.obj
        with pdf.open_metadata(set_pikepdf_as_editor=False,update_docinfo=False) as metadata:
            assert metadata['dc:title']=='output'
            assert metadata['xmpMM:DocumentID']!=metadata['xmpMM:InstanceID']
            assert metadata['xmp:ModifyDate']==metadata['xmp:MetadataDate']
            assert metadata['{http://ns.adobe.com/xap/1.0/t/pg/}NPages']=='1'
            assert metadata['{http://ns.adobe.com/xap/1.0/t/pg/}HasVisibleTransparency']=='False'


@pytest.mark.parametrize('commands', [
    b'2 w 10 20 30 40 re S',
    b'10 20 30 40 re W n 0 0 100 200 re f',
])
def test_complex_artwork_keeps_group_and_artbox(tmp_path,commands):
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai';document(source,commands)
    convert(source,output,raster_fallback=False)
    with pikepdf.open(output) as pdf:
        assert '/Group' in pdf.pages[0].obj
        assert list(pdf.pages[0].ArtBox)==[0,0,100,200]


def test_transparency_keeps_pdf_group_and_original_artbox(tmp_path):
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai';document(source)
    with pikepdf.open(source,allow_overwriting_input=True) as pdf:
        page=pdf.pages[0]
        page.Resources.ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(ca=.5))
        page.Contents=pdf.make_stream(b'/A gs /S cs 1 scn 10 20 30 40 re f')
        pdf.save(source)
    convert(source,output,raster_fallback=False)
    with pikepdf.open(output) as pdf:
        assert '/Group' in pdf.pages[0].obj
        assert list(pdf.pages[0].ArtBox)==[0,0,100,200]


def test_curve_bounds_use_actual_extrema(tmp_path):
    source=tmp_path/'source.pdf';document(source,b'0 0 m 0 10 10 10 10 0 c h f')
    with pikepdf.open(source) as pdf:
        drawing=read_drawing(pdf.pages[0],root=pdf.Root)
        assert fill_artwork_bounds(drawing)==pytest.approx((0,0,10,7.5))


def test_artwork_outside_page_does_not_create_invalid_artbox(tmp_path):
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai';document(source,b'-10 -10 120 220 re f')
    convert(source,output,raster_fallback=False)
    with pikepdf.open(output) as pdf:
        assert list(pdf.pages[0].ArtBox)==[0,0,100,200]


def test_custom_title_and_layer_names_are_preserved(tmp_path):
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai';document(source,title='Custom artwork')
    with pikepdf.open(source,allow_overwriting_input=True) as pdf:
        layer=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.OCG,Name='背景'))
        pdf.Root.OCProperties=pikepdf.Dictionary(OCGs=[layer],D=pikepdf.Dictionary(Order=[layer]))
        page=pdf.pages[0];page.Resources.Properties=pikepdf.Dictionary(L=layer)
        page.Contents=pdf.make_stream(b'/OC /L BDC /S cs 1 scn 10 20 30 40 re f EMC')
        pdf.save(source)
    report=convert(source,output,raster_fallback=False)
    assert report['layers'][0]['name']=='背景'
    with pikepdf.open(output) as pdf:
        assert str(pdf.docinfo['/Title'])=='Custom artwork'
        assert str(pdf.docinfo['/Author'])=='Designer'


def test_custom_pdf_viewer_settings_are_preserved(tmp_path):
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai';document(source)
    with pikepdf.open(source,allow_overwriting_input=True) as pdf:
        pdf.Root.PageLayout=pikepdf.Name.TwoPageRight
        pdf.Root.ViewerPreferences=pikepdf.Dictionary(Direction=pikepdf.Name.R2L,DisplayDocTitle=True)
        pdf.save(source)
    convert(source,output,raster_fallback=False)
    with pikepdf.open(output) as pdf:
        assert str(pdf.Root.PageLayout)=='/TwoPageRight'
        assert str(pdf.Root.ViewerPreferences.Direction)=='/R2L'
        assert pdf.Root.ViewerPreferences.DisplayDocTitle


def test_toyo_xmp_records_actual_lab_swatch(tmp_path):
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai';document(source)
    with pikepdf.open(source,allow_overwriting_input=True) as pdf:
        pdf.pages[0].Resources.ColorSpace.S[1]=pikepdf.Name('/CF 10001')
        pdf.save(source)
    report=convert(source,output,raster_fallback=False)
    lab=report['spots'][0]['values']
    with pikepdf.open(output) as pdf:
        xml=ET.fromstring(pdf.Root.Metadata.read_bytes())
        graphic='{http://ns.adobe.com/xap/1.0/g/}'
        assert xml.find('.//'+graphic+'mode').text=='LAB'
        assert [float(xml.find('.//'+graphic+key).text) for key in ('L','A','B')]==lab
        assert '/Group' in pdf.pages[0].obj


def test_combined_output_keeps_page_order_and_page_thumbnails(tmp_path):
    source=tmp_path/'source.pdf';output=tmp_path/'output.ai';document(source)
    with pikepdf.open(source,allow_overwriting_input=True) as pdf:
        pdf.pages.append(pdf.pages[0]);pdf.save(source)
    reports=convert_document(source,output,pages=[2,1],raster_fallback=False)
    assert [report['page'] for report in reports]==[2,1]
    with pikepdf.open(output) as pdf:
        assert all('/Thumb' in page.obj and '/Group' not in page.obj for page in pdf.pages)
        assert all(list(page.ArtBox)==[10,20,40,60] for page in pdf.pages)
        with pdf.open_metadata(set_pikepdf_as_editor=False,update_docinfo=False) as metadata:
            assert metadata['{http://ns.adobe.com/xap/1.0/t/pg/}NPages']=='2'
