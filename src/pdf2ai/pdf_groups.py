"""Make a page knockout explicit as a Form group for consistent PDF rendering."""
import pikepdf


def explicit_page_knockout(pdf,page):
    group=page.obj.get('/Group')
    if (group is None or not group.get('/K',False) or str(group.get('/S'))!='/Transparency'
            or str(group.get('/CS')) not in ('/DeviceRGB','/DeviceCMYK')
            or pdf.Root.get('/OCProperties') is not None):return False
    contents=page.obj.get('/Contents')
    streams=list(contents) if isinstance(contents,pikepdf.Array) else [contents]
    if any(not isinstance(stream,pikepdf.Stream) for stream in streams):return False
    form=pdf.make_stream(b'\n'.join(stream.read_bytes() for stream in streams))
    form.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject,Subtype=pikepdf.Name.Form,
        BBox=list(page.obj.get('/CropBox',page.MediaBox)),
        Resources=page.obj.get('/Resources',pikepdf.Dictionary()),Group=pikepdf.Dictionary(group)))
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Pdf2AiPageGroup=form))
    page.Contents=pdf.make_stream(b'/Pdf2AiPageGroup Do\n')
    outer=pikepdf.Dictionary(group);outer.K=False;outer.I=False;page.Group=outer
    return True
