"""End-to-end regressions for staged publication, merge inspection and expanded drawing."""
import json
from pathlib import Path

import pikepdf
import pymupdf
import pytest
from PIL import Image, ImageChops, ImageStat

from pdf2ai.cli import main
from pdf2ai.native import convert
from pdf2ai.preflight import inspect_combination
from pdf2ai.vector import read_drawing


def source_pdf(path, contents=(b'10 10 30 30 re f',), size=(100,100)):
    pdf = pikepdf.new()
    for content in contents:
        page = pdf.add_blank_page(page_size=size)
        page.Contents = pdf.make_stream(content)
    pdf.save(path)


def test_late_conversion_failure_leaves_all_previous_outputs_and_report(tmp_path):
    source = tmp_path/'source.pdf'
    source_pdf(source,(b'10 10 30 30 re f', b'0 w 10 10 m 80 80 l S'))
    old = {tmp_path/'page_001.ai':b'old1',tmp_path/'page_002.ai':b'old2',tmp_path/'report.json':b'old report'}
    for path,data in old.items():path.write_bytes(data)
    assert main([str(source),'--pages','all','-o',str(tmp_path/'page.ai'),'--strict','--overwrite',
                 '--report',str(tmp_path/'report.json')]) == 1
    assert all(path.read_bytes()==data for path,data in old.items())
    assert not list(tmp_path.glob('.pdf2ai-*'))


def test_report_publication_failure_rolls_back_ai(tmp_path,monkeypatch):
    import pdf2ai.batch_publish as publisher
    source = tmp_path/'source.pdf';source_pdf(source)
    ai = tmp_path/'out.ai';report=tmp_path/'report.json'
    ai.write_bytes(b'old ai');report.write_bytes(b'old report')
    real_replace=publisher.os.replace
    def fail_report(src,dst):
        if Path(dst)==report and Path(src).parent.name.startswith('.pdf2ai-cli-'):
            raise OSError('simulated report failure')
        return real_replace(src,dst)
    monkeypatch.setattr(publisher.os,'replace',fail_report)
    assert main([str(source),'-o',str(ai),'--report',str(report),'--overwrite'])==1
    assert ai.read_bytes()==b'old ai' and report.read_bytes()==b'old report'
    assert not list(tmp_path.glob('.pdf2ai-*'))


def test_staged_report_names_final_destinations(tmp_path):
    source=tmp_path/'source.pdf';source_pdf(source)
    report=tmp_path/'report.json';ai=tmp_path/'out.ai'
    assert main([str(source),'-o',str(ai),'--report',str(report)])==0
    assert json.loads(report.read_text())[0]['output']==str(ai)
    assert not list(tmp_path.glob('.pdf2ai-*'))


def test_merge_inspection_checks_canvas_without_output(tmp_path):
    source=tmp_path/'source.pdf';source_pdf(source,(b'10 10 30 30 re f',)*3,size=(9000,9000))
    rows=inspect_combination(source)
    assert all(row['native_supported'] and row['combined_constraints_checked'] for row in rows)
    assert all('キャンバス' in row['combined_blocker'] for row in rows)
    assert not list(tmp_path.glob('*.ai'))


def test_merge_inspection_checks_spot_conflict_and_cli(tmp_path,capsys):
    source=tmp_path/'spots.pdf';pdf=pikepdf.new()
    for full in ([1,0,0,0],[0,1,0,0]):
        page=pdf.add_blank_page(page_size=(100,100))
        page.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(S=pikepdf.Array([
            pikepdf.Name.Separation,pikepdf.Name('/Same'),pikepdf.Name.DeviceCMYK,
            pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0]*4,C1=full,N=1)])))
        page.Contents=pdf.make_stream(b'/S cs 1 scn 10 10 30 30 re f')
    pdf.save(source)
    assert main([str(source),'--check','--combine'])==1
    rows=json.loads(capsys.readouterr().out)
    assert all('特色' in row['combined_blocker'] for row in rows)
    assert not list(tmp_path.glob('*.ai'))


def test_merge_inspection_success_preserves_selected_order(tmp_path):
    source=tmp_path/'source.pdf';source_pdf(source,(b'10 10 30 30 re f',)*3)
    rows=inspect_combination(source,[3,1],page_labels=[9,7])
    assert [row['page'] for row in rows]==[9,7]
    assert all(row['native_supported'] and row['combined_constraints_checked'] for row in rows)
    assert all('artboard_box' in row for row in rows)


@pytest.mark.parametrize('form',[False,True])
def test_inline_rgb_image_preserves_pixels_and_stays_vector(tmp_path,form):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    stream=b'q 40 0 0 40 20 20 cm BI /W 1 /H 1 /BPC 8 /CS /RGB ID \xff\0\0 EI Q'
    if form:
        obj=pdf.make_stream(stream);obj.Subtype=pikepdf.Name.Form;obj.BBox=[0,0,100,100]
        obj.Resources=pikepdf.Dictionary()
        page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(F=obj));page.Contents=pdf.make_stream(b'/F Do')
    else:page.Contents=pdf.make_stream(stream)
    source=tmp_path/'source.pdf';pdf.save(source)
    with pikepdf.open(source) as opened:
        drawing=read_drawing(opened.pages[0]);assert drawing.images[0].pixels==b'\xff\0\0'
    assert convert(source,tmp_path/'out.ai',raster_fallback=False)['images']==1


@pytest.mark.parametrize('space,bits,raw,expected',[
    (pikepdf.Name.DeviceRGB,8,b'\xff\x40\0',b'\xff\x40\0'),
    (pikepdf.Name.DeviceGray,4,b'\xf0',b'\xff'),
    (pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name('/Base'),1,pikepdf.String(b'\0\0\0\xff\0\0')]),1,b'\x80',b'\xff\0\0'),
])
def test_image_aliases_resolve_without_mutating_source(space,bits,raw,expected):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100));image=pdf.make_stream(raw)
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=1,Height=1,BitsPerComponent=bits,ColorSpace=pikepdf.Name('/Alias')))
    page.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(Alias=space,Base=pikepdf.Name.DeviceRGB),XObject=pikepdf.Dictionary(I=image))
    page.Contents=pdf.make_stream(b'40 0 0 40 20 20 cm /I Do')
    result=read_drawing(page)
    assert result.images[0].pixels==expected
    assert str(image.ColorSpace)=='/Alias'


def render(pdf,dpi):
    with pymupdf.open(stream=pdf, filetype='pdf') as doc:
        pix=doc[0].get_pixmap(matrix=pymupdf.Matrix(dpi/72,dpi/72),alpha=False)
        return Image.frombytes('RGB',(pix.width,pix.height),pix.samples)


@pytest.mark.parametrize('content',[
    b'2 0 0 1 0 0 cm 8 w 0 J [0 8] 0 d 10 20 m 40 20 l S',
    b'2 0 0 1 0 0 cm 8 w 2 J [0 8] 0 d 10 20 m 40 20 l S',
    b'2 0 0 1 0 0 cm 8 w 1 J 10 20 m 10 20 l S',
    b'2 0 0 1 0 0 cm 8 w 0 j 10 20 m 40 20 l 10 20 l S',
    b'2 0 0 1 0 0 cm 8 w 1 j 10 20 m 40 20 l 10 20 l S',
    b'2 0 0 1 0 0 cm 8 w 2 j 10 20 m 40 20 l 10 20 l S',
])
@pytest.mark.parametrize('dpi',[144,600])
def test_new_stroke_outlines_match_original_renderer(content,dpi):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,60));page.Contents=pdf.make_stream(content)
    import io
    original=io.BytesIO();pdf.save(original)
    drawing=read_drawing(page)
    commands=[]
    for item in drawing.paths:
        assert item.paint=='fill'
        for path in item.paths:
            for op,values in path.commands:
                commands.append(' '.join(str(v) for v in values)+' '+{'m':'m','L':'l','C':'c'}[op])
            if path.closed:commands.append('h')
        commands.append('f')
    page.Contents=pdf.make_stream(' '.join(commands).encode())
    outlined=io.BytesIO();pdf.save(outlined)
    a,b=render(original.getvalue(),dpi),render(outlined.getvalue(),dpi)
    error=sum(ImageStat.Stat(ImageChops.difference(a,b)).mean)/3
    assert error<0.15


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('fallback',[False,True])
def test_password_pdf_conversion_and_inspection_preserve_input(tmp_path,combined,fallback,capsys):
    source=tmp_path/'secret.pdf';source_pdf(source,(b'0 w 10 10 m 80 80 l S' if fallback else b'10 10 30 30 re f',))
    with pikepdf.open(source,allow_overwriting_input=True) as pdf:
        pdf.save(source,encryption=pikepdf.Encryption(owner='owner-secret',user='reader-secret',R=6))
    original=source.read_bytes();password=tmp_path/'password.txt';password.write_text('reader-secret\n')
    output=tmp_path/'out.ai';report=tmp_path/'report.json'
    args=[str(source),'-o',str(output),'--password-file',str(password),'--report',str(report),'--raster-dpi','72']
    if combined:args.append('--combine')
    assert main(args)==0
    rows=json.loads(report.read_text());assert rows[0]['input']==str(source)
    assert rows[0]['rasterized']==fallback
    with pikepdf.open(output) as pdf:assert not pdf.is_encrypted
    assert source.read_bytes()==original
    assert 'reader-secret' not in report.read_text()+capsys.readouterr().out
    check=[str(source),'--check','--password-file',str(password),'--raster-dpi','72']
    if combined:check.append('--combine')
    assert main(check)==int(fallback)


def test_wrong_password_does_not_publish_or_leak_password(tmp_path,capsys):
    source=tmp_path/'secret.pdf';source_pdf(source)
    with pikepdf.open(source,allow_overwriting_input=True) as pdf:
        pdf.save(source,encryption=pikepdf.Encryption(owner='owner',user='reader',R=6))
    password=tmp_path/'password.txt';password.write_text('private-wrong-password')
    assert main([str(source),'--password-file',str(password),'--combine'])==1
    assert not source.with_suffix('.ai').exists()
    assert 'private-wrong-password' not in capsys.readouterr().err


@pytest.mark.parametrize('combined',[False,True])
def test_annotation_flattening_keeps_vectors_and_visual_appearance(tmp_path,combined):
    source=tmp_path/'annotations.pdf'
    with pymupdf.open() as document:
        page=document.new_page(width=100,height=100)
        page.draw_rect(pymupdf.Rect(10,10,40,40),color=None,fill=(1,0,0))
        annotation=page.add_rect_annot(pymupdf.Rect(50,50,90,90))
        annotation.set_colors(stroke=(0,0,1));annotation.update()
        document.save(source)
    original=source.read_bytes();output=tmp_path/'out.ai'
    args=[str(source),'-o',str(output),'--flatten-annotations','--strict']
    if combined:args.append('--combine')
    assert main(args)==0
    assert source.read_bytes()==original
    with pikepdf.open(output) as pdf:assert not pdf.pages[0].get('/Annots')
    a,b=render(original,144),render(output.read_bytes(),144)
    assert ImageChops.difference(a,b).getbbox() is None


def test_combine_outline_text_preprocesses_once_and_keeps_page_order(tmp_path,monkeypatch):
    from pdf2ai.multiboard import convert_document
    source=tmp_path/'source.pdf';source_pdf(source,(b'10 10 30 30 re f',)*3)
    calls=[]
    def outline(src,dst,executable):
        calls.append(src)
        Path(dst).write_bytes(Path(src).read_bytes())
    monkeypatch.setattr('pdf2ai.preprocess.outline_pdf',outline)
    rows=convert_document(source,tmp_path/'out.ai',pages=[3,1],outline_text=True)
    assert len(calls)==1 and [r['page'] for r in rows]==[3,1]
    assert all(r['text_outlined'] for r in rows)


def test_smaller_aligned_soft_mask():
    from pdf2ai.vector import read_image, State
    pdf=pikepdf.new()
    image=pdf.make_stream(b'\x55\xaa\x55\xaa')
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=4,Height=1,BitsPerComponent=8,
        ColorSpace=pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name.DeviceRGB,255,
            pikepdf.String(bytes(v for i in range(256) for v in (i,i,i)))])))
    mask=pdf.make_stream(b'\x80\xff')
    mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=2,Height=1,BitsPerComponent=8,
        ColorSpace=pikepdf.Name.DeviceGray))
    image.SMask=mask
    result=read_image(image,State())
    assert result.alpha==b'\x80\x80\xff\xff'
    assert result.pixels==bytes([85]*3+[170]*3+[85]*3+[170]*3)
    assert int(image.SMask.Width)==2


@pytest.mark.parametrize('combined',[False,True])
def test_toyo_cmyk_preview_matches_editable_lab_and_dic_stays_separate(tmp_path,combined):
    from pdf2ai.toyo import toyo_color
    from pdf2ai.multiboard import convert_document
    source=tmp_path/'toyo.pdf';pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    def space(name):
        return pikepdf.Array([pikepdf.Name.Separation,pikepdf.Name('/'+name),pikepdf.Name.DeviceCMYK,
            pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0]*4,C1=[1,0,0,0],N=1)])
    page.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(T=space('TOYO 1'),D=space('DIC 1')))
    page.Contents=pdf.make_stream(b'/T cs .5 scn 10 10 30 30 re f /D cs 1 scn 50 10 30 30 re f');pdf.save(source)
    original=source.read_bytes();output=tmp_path/'out.ai'
    if combined:convert_document(source,output,raster_fallback=False)
    else:convert(source,output,raster_fallback=False)
    with pikepdf.open(output) as result:
        spaces=result.pages[0].Resources.ColorSpace
        assert str(spaces.T[2][0])=='/Lab'
        assert list(map(float,spaces.T[3].C1))==pytest.approx(toyo_color('TOYO 1')['lab'])
        assert str(spaces.D[2])=='/DeviceCMYK'
        assert list(map(float,spaces.D[3].C1))==pytest.approx([0,.16,.17,0])
    assert source.read_bytes()==original


@pytest.mark.parametrize('isolated,knockout',[(True,False),(False,True),(True,True)])
def test_same_space_page_groups_preserve_native_group_attributes(tmp_path,isolated,knockout):
    from pdf2ai.native import read_private
    source=tmp_path/'groups.pdf';pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB,I=isolated,K=knockout)
    page.Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(ca=.5)))
    page.Contents=pdf.make_stream(b'/A gs 1 0 0 rg 10 10 60 60 re f 0 0 1 rg 30 30 60 60 re f');pdf.save(source)
    output=tmp_path/'out.ai';report=convert(source,output,raster_fallback=False)
    assert report['transparency_groups']==1
    with pikepdf.open(output) as result:
        assert f'0 1 {int(isolated)} {1 if knockout else 2} 0 Xy'.encode() in read_private(result)


def test_timeout_preserves_output_and_cleans_staging(tmp_path):
    source=tmp_path/'source.pdf';source_pdf(source)
    output=tmp_path/'out.ai';output.write_bytes(b'previous')
    assert main([str(source),'-o',str(output),'--overwrite','--timeout','0.001'])==1
    assert output.read_bytes()==b'previous'
    assert not list(tmp_path.glob('.pdf2ai-*'))


def test_timeout_worker_can_publish_normal_conversion(tmp_path):
    source=tmp_path/'source.pdf';source_pdf(source)
    output=tmp_path/'out.ai'
    assert main([str(source),'-o',str(output),'--timeout','30'])==0
    assert output.exists()


def test_keyboard_interrupt_restores_existing_output(tmp_path,monkeypatch):
    source=tmp_path/'source.pdf';source_pdf(source)
    output=tmp_path/'out.ai';output.write_bytes(b'previous')
    def interrupt(*args,**kwargs):raise KeyboardInterrupt()
    monkeypatch.setattr('pdf2ai.cli.convert',interrupt)
    assert main([str(source),'-o',str(output),'--overwrite'])==130
    assert output.read_bytes()==b'previous'
    assert not list(tmp_path.glob('.pdf2ai-*'))


def test_shared_image_aliases_are_normalized_per_resource_scope(tmp_path):
    from pdf2ai.multiboard import convert_document
    pdf=pikepdf.new();image=pdf.make_stream(b'\x80')
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=1,Height=1,BitsPerComponent=8,ColorSpace=pikepdf.Name('/Alias')))
    objects=pdf.make_indirect(pikepdf.Dictionary(I=image))
    palette=pikepdf.String(bytes(v for i in range(256) for v in (i,0,0)))
    for space in (pikepdf.Name.DeviceGray,pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name.DeviceRGB,255,palette])):
        page=pdf.add_blank_page(page_size=(100,100))
        page.Resources=pikepdf.Dictionary(XObject=objects,ColorSpace=pikepdf.Dictionary(Alias=space))
        page.Contents=pdf.make_stream(b'40 0 0 40 20 20 cm /I Do')
    source=tmp_path/'source.pdf';pdf.save(source);original=source.read_bytes()
    output=tmp_path/'out.ai';reports=convert_document(source,output,raster_fallback=False)
    assert all(not row['rasterized'] for row in reports)
    with pikepdf.open(output) as result:
        first=result.pages[0].Resources.XObject.I
        second=result.pages[1].Resources.XObject.I
        assert str(first.ColorSpace)=='/DeviceGray'
        assert str(second.ColorSpace[0])=='/Indexed'
        assert first.objgen!=second.objgen
    assert source.read_bytes()==original


def test_separate_preflight_reads_input_once_and_reports_progress(tmp_path,monkeypatch):
    from pdf2ai.preflight import inspect_document
    source=tmp_path/'source.pdf';source_pdf(source,(b'10 10 30 30 re f',)*3)
    original_open=pikepdf.open;opened=[]
    def count_open(path,*args,**kwargs):
        opened.append(path);return original_open(path,*args,**kwargs)
    monkeypatch.setattr(pikepdf,'open',count_open)
    events=[]
    rows=inspect_document(source,progress=lambda *event:events.append(event))
    assert len(rows)==3 and len(opened)==1
    assert events==[(1,1,3),(2,2,3),(3,3,3)]


def test_indexed_matte_uses_palette_index_and_requires_matching_size():
    from pdf2ai.vector import read_image,State,ConversionError
    pdf=pikepdf.new();image=pdf.make_stream(b'\x01\x01')
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=2,Height=1,BitsPerComponent=8,
        ColorSpace=pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name.DeviceRGB,1,pikepdf.String(b'\0\0\0\x80\0\0')])))
    mask=pdf.make_stream(b'\x80\xff');mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,
        Width=2,Height=1,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray,Matte=[0]))
    image.SMask=mask
    result=read_image(image,State())
    assert result.pixels==b'\xff\0\0\x80\0\0'
    mask.Width=1
    with pytest.raises(ConversionError,match='matching image dimensions'):read_image(image,State())


@pytest.mark.parametrize('kind',['ai','report','check-report'])
def test_password_file_is_never_overwritten_by_outputs(tmp_path,kind):
    source=tmp_path/'source.pdf';source_pdf(source)
    password=tmp_path/('password.ai' if kind=='ai' else 'password.json');password.write_text('private-password')
    args=[str(source),'--password-file',str(password),'--overwrite']
    args+=['-o',str(password)] if kind=='ai' else ['--report',str(password)]
    if kind=='check-report':args.append('--check')
    assert main(args)==1
    assert password.read_text()=='private-password'
    assert not source.with_suffix('.ai').exists()


def test_move_only_stroke_is_empty_but_zero_length_curve_has_round_cap():
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Contents=pdf.make_stream(b'2 0 0 1 0 0 cm 1 J 8 w 10 20 m S')
    assert not read_drawing(page).paths
    page.Contents=pdf.make_stream(b'2 0 0 1 0 0 cm 1 J 8 w 10 20 m 10 20 10 20 10 20 c S')
    assert len(read_drawing(page).paths)==1


@pytest.mark.parametrize('dimensions',[(3,2,2,3),(2,2,4,4),(4,4,2,2)])
def test_different_mask_grids_keep_all_original_sample_boundaries(dimensions):
    from pdf2ai.vector import read_image,State
    from math import lcm
    width,height,mw,mh=dimensions;pdf=pikepdf.new()
    image=pdf.make_stream(bytes(range(width*height)))
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=width,Height=height,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray))
    values=bytes(range(10,10+mw*mh));mask=pdf.make_stream(values)
    mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=mw,Height=mh,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray))
    image.SMask=mask;result=read_image(image,State())
    assert (result.width,result.height)==(lcm(width,mw),lcm(height,mh))
    for y in range(result.height):
        for x in range(result.width):
            i=y*result.width+x
            assert result.pixels[i]==(y*height//result.height)*width+x*width//result.width
            assert result.alpha[i]==values[(y*mh//result.height)*mw+x*mw//result.width]


def test_expanding_mask_grid_is_bounded_before_decoding():
    from pdf2ai.vector import read_image,State,ConversionError
    pdf=pikepdf.new();image=pdf.make_stream(b'')
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=1000,Height=1000,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray))
    mask=pdf.make_stream(b'');mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=999,Height=999,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray));image.SMask=mask
    with pytest.raises(ConversionError,match='sample grid exceeds'):read_image(image,State())


def test_knockout_pdf_view_matches_explicit_group_and_keeps_original(tmp_path):
    from pdf2ai.pdf_groups import explicit_page_knockout
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(120,100))
    page.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB,K=True)
    page.Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(ca=.5)))
    page.Contents=pdf.make_stream(b'/A gs 1 0 0 rg 10 10 70 60 re f 0 0 1 rg 40 30 70 60 re f')
    source=tmp_path/'source.pdf';pdf.save(source);original=source.read_bytes()
    output=tmp_path/'out.ai';convert(source,output,raster_fallback=False)
    assert explicit_page_knockout(pdf,page)
    expected=tmp_path/'expected.pdf';pdf.save(expected)
    assert ImageChops.difference(render(expected.read_bytes(),144),render(output.read_bytes(),144)).getbbox() is None
    with pikepdf.open(output) as result:
        assert not result.pages[0].Group.K
        assert result.pages[0].Resources.XObject.Pdf2AiPageGroup.Group.K
    assert source.read_bytes()==original


@pytest.mark.parametrize('adjust',[False,True])
def test_stroke_adjustment_does_not_rasterize_fill_only_artwork(tmp_path,adjust):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(SA=adjust)))
    page.Contents=pdf.make_stream(b'/A gs 10 10 30 30 re f')
    source=tmp_path/'source.pdf';pdf.save(source)
    assert not convert(source,tmp_path/'out.ai',raster_fallback=False)['rasterized']


def test_device_dependent_stroke_adjustment_still_rejected():
    from pdf2ai.vector import ConversionError
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,100))
    page.Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(SA=True)))
    page.Contents=pdf.make_stream(b'/A gs 10 10 m 80 80 l S')
    with pytest.raises(ConversionError,match='stroke adjustment'):read_drawing(page)


def test_canvas_inspection_and_conversion_try_full_width_before_rejecting(tmp_path):
    from pdf2ai.multiboard import convert_document
    pdf=pikepdf.new()
    for width in (100,10000):
        page=pdf.add_blank_page(page_size=(width,10000));page.Contents=pdf.make_stream(b'10 10 30 30 re f')
    source=tmp_path/'large.pdf';pdf.save(source)
    inspected=inspect_combination(source)
    assert not any(row.get('combined_blocker') for row in inspected)
    assert all(row['native_supported'] for row in inspected)
    boxes=[row['artboard_box'] for row in inspected]
    assert boxes[0][1]==boxes[1][1] and boxes[0][3]==boxes[1][3]
    assert max(box[2] for box in boxes)-min(box[0] for box in boxes)==10120
    reports=convert_document(source,tmp_path/'out.ai',raster_fallback=False)
    assert [row['artboard_box'] for row in reports]==boxes
