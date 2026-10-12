"""Standard Illustrator document settings without copying another document's caches."""
from io import BytesIO
import base64
import uuid
import xml.etree.ElementTree as ET

import pikepdf
from fontTools.pens.boundsPen import BoundsPen

from .vector import Color, GroupBoundary, PaintedPath, Raster


def fill_artwork_bounds(drawing):
    """Exact geometric bounds for unclipped fill-only artwork, otherwise unknown.

    Retain existing page bounds for strokes, clipping, images and group effects;
    a loose estimate must not become a tight PDF ArtBox that cuts off artwork.
    """
    items = drawing.items or drawing.paths
    if not items or any(not isinstance(item, PaintedPath) or item.paint != 'fill'
                        or item.state.clips or item.state.fill_alpha != 1
                        or item.state.blend_mode != 'Normal'
                        or item.state.layer is not None and not item.state.layer.visible
                        for item in items):
        return None
    pen = BoundsPen(None)
    for item in items:
        for path in item.paths:
            for operator, coords in path.commands:
                if operator == 'm':
                    pen.moveTo(coords)
                elif operator == 'L':
                    pen.lineTo(coords)
                elif operator == 'C':
                    pen.curveTo(coords[:2], coords[2:4], coords[4:])
                else:
                    return None
            if path.closed:
                pen.closePath()
            else:
                pen.endPath()
    if pen.bounds is None:
        return None
    x0, y0, x1, y1 = pen.bounds
    # Illustrator artwork can extend outside the canvas. PDF ArtBox cannot.
    if not (drawing.box[0] <= x0 < x1 <= drawing.box[2]
            and drawing.box[1] <= y0 < y1 <= drawing.box[3]):
        return None
    return pen.bounds


def profiled_spot_resources(resources):
    """Keep the original blending context for profile-based spot alternates."""
    pending=[resources];seen=set()
    while pending:
        resource=pending.pop()
        if not isinstance(resource,pikepdf.Dictionary):continue
        if resource.objgen!=(0,0):
            if resource.objgen in seen:continue
            seen.add(resource.objgen)
        spaces=resource.get('/ColorSpace',{})
        if not isinstance(spaces,(dict,pikepdf.Dictionary)):return True
        for space in spaces.values():
            if (isinstance(space,pikepdf.Array) and len(space)==4 and str(space[0])=='/Separation'
                    and isinstance(space[2],pikepdf.Array) and len(space[2]) and str(space[2][0])=='/ICCBased'):
                return True
        objects=resource.get('/XObject',{})
        if not isinstance(objects,(dict,pikepdf.Dictionary)):return True
        for obj in objects.values():
            if isinstance(obj,pikepdf.Stream) and str(obj.get('/Subtype'))=='/Form':
                if obj.objgen in seen:continue
                seen.add(obj.objgen);pending.append(obj.get('/Resources'))
    return False


def align_page_settings(page, drawing):
    bounds = fill_artwork_bounds(drawing)
    if bounds is not None and int(page.obj.get('/Rotate', 0)) == 0 and float(page.obj.get('/UserUnit', 1)) == 1:
        page.obj.ArtBox = pikepdf.Array(bounds)
    group = page.obj.get('/Group')
    if drawing.color_model != 'CMYK':
        return
    if any(spot.lab is not None for spot in drawing.spots) and profiled_spot_resources(page.Resources):
        return
    def opaque_cmyk(item):
        if not isinstance(item, PaintedPath) or item.state.blend_mode != 'Normal':
            return False
        paints = []
        if item.paint != 'stroke':
            paints.append((item.state.fill,item.state.fill_alpha))
        if item.paint != 'fill':
            paints.append((item.state.stroke,item.state.stroke_alpha))
        return all(alpha == 1 and isinstance(color,Color)
                   and color.model in ('CMYK','Gray','Spot')
                   for color,alpha in paints)
    # Adobe omits the redundant CMYK page blending group for opaque process
    # and registered Lab/CMYK spot paths, including clipped/stroked paths. Retain the actual
    # overprint states in the resources and editing stream.
    if ((group is None or str(group.get('/S')) == '/Transparency'
         and str(group.get('/CS')) == '/DeviceCMYK'
         and not group.get('/I', False) and not group.get('/K', False))
            and all(opaque_cmyk(item) for item in drawing.items or drawing.paths)):
        if group is not None:
            del page.obj['/Group']
        # Illustrator's PDF export uses Perceptual for unprofiled CMYK.
        # Leave explicit ri operators/ExtGState /RI settings able to override it.
        page.contents_add(b'/Perceptual ri\n', prepend=True)
        from .pdf_path_defaults import align_pdf_fill_paths
        align_pdf_fill_paths(page)


def add_page_thumbnails(pdf):
    """Small PDF page previews; rendered from the actual output representation."""
    import pymupdf
    buffer = BytesIO()
    pdf.save(buffer)
    with pymupdf.open(stream=buffer.getvalue(), filetype='pdf') as document:
        for index, page in enumerate(pdf.pages):
            view = document[index]
            scale = 52/max(view.rect.width, view.rect.height)
            pixmap = view.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
            thumbnail = pdf.make_stream(pixmap.samples)
            thumbnail.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
                Width=pixmap.width, Height=pixmap.height, BitsPerComponent=8, ColorSpace=pikepdf.Name.DeviceRGB))
            page.obj.Thumb = thumbnail


def set_document_metadata(pdf, output, moment, drawings):
    if len(pdf.pages) == 1 and str(pdf.Root.get('/PageLayout')) == '/SinglePage':
        del pdf.Root['/PageLayout']
    preferences = pdf.Root.get('/ViewerPreferences')
    if isinstance(preferences, pikepdf.Dictionary):
        for key in ('/Direction', '/PageDirection'):
            if str(preferences.get(key)) == '/L2R':
                del preferences[key]
        if not preferences:
            del pdf.Root['/ViewerPreferences']
    timestamp = moment.strftime('D:%Y%m%d%H%M%SZ')
    title = str(pdf.docinfo.get('/Title', ''))
    pdf.docinfo['/ModDate'] = timestamp
    if '/CreationDate' not in pdf.docinfo:
        pdf.docinfo['/CreationDate'] = timestamp
    for page in pdf.pages:
        page.obj.LastModified = timestamp
        if '/Rotate' in page.obj and int(page.obj.Rotate) == 0:
            del page.obj['/Rotate']
        if '/ProcSet' in page.Resources:
            del page.Resources['/ProcSet']
    with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
        xmp_title = metadata.get('dc:title')
        title = title or xmp_title or output.stem
        pdf.docinfo['/Title'] = title
        if not xmp_title:
            metadata['dc:title'] = title
        metadata['dc:format'] = 'application/pdf'
        date = moment.isoformat(timespec='seconds')
        if 'xmp:CreateDate' not in metadata:
            metadata['xmp:CreateDate'] = date
        metadata['xmp:ModifyDate'] = date
        metadata['xmp:MetadataDate'] = date
        original_id = metadata.get('xmpMM:OriginalDocumentID') or metadata.get('xmpMM:DocumentID')
        document_id = 'xmp.did:'+str(uuid.uuid4())
        metadata['xmpMM:DocumentID'] = document_id
        metadata['xmpMM:OriginalDocumentID'] = original_id or document_id
        metadata['xmpMM:InstanceID'] = 'uuid:'+str(uuid.uuid4())
        page_namespace = '{http://ns.adobe.com/xap/1.0/t/pg/}'
        # Illustrator counts the one editable document here, including when
        # its PDF-compatible representation contains several artboard pages.
        metadata[page_namespace+'NPages'] = '1'
        metadata['xmpMM:RenditionClass'] = 'proof:pdf'
        metadata['{http://ns.adobe.com/illustrator/1.0/}Type'] = 'Document'
        metadata['{http://ns.adobe.com/illustrator/1.0/}IsFileSavedViaInstantSave'] = 'False'
        if drawings:
            items = [item for drawing in drawings for item in drawing.items or drawing.paths
                     if item.state.layer is None or item.state.layer.visible]
            def has_transparency(item):
                if isinstance(item, GroupBoundary) or item.state.blend_mode != 'Normal':
                    return True
                if isinstance(item, PaintedPath):
                    return ((item.paint != 'stroke' and item.state.fill_alpha != 1)
                            or (item.paint != 'fill' and item.state.stroke_alpha != 1))
                if isinstance(item, Raster):
                    return (item.state.fill_alpha != 1 or item.alpha is not None
                            and item.alpha.count(255) != len(item.alpha))
                return False
            def has_overprint(item):
                if isinstance(item, PaintedPath):
                    return ((item.paint != 'stroke' and item.state.fill_overprint)
                            or (item.paint != 'fill' and item.state.stroke_overprint))
                return isinstance(item, Raster) and item.state.fill_overprint
            transparent = any(has_transparency(item) for item in items)
            overprint = any(has_overprint(item) for item in items)
            metadata[page_namespace+'HasVisibleTransparency'] = str(transparent)
            metadata[page_namespace+'HasVisibleOverprint'] = str(overprint)


def set_structured_metadata(pdf, drawings, meta, *, artboard_boxes=None):
    """Write actual page/swatch/preview data in the reference AI's XMP structures."""
    from PIL import Image
    namespaces = {
        'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
        'xmp': 'http://ns.adobe.com/xap/1.0/',
        'xmpTPg': 'http://ns.adobe.com/xap/1.0/t/pg/',
        'xmpG': 'http://ns.adobe.com/xap/1.0/g/',
        'stDim': 'http://ns.adobe.com/xap/1.0/sType/Dimensions#',
        'xmpGImg': 'http://ns.adobe.com/xap/1.0/g/img/',
    }
    def tag(prefix, name):
        return '{'+namespaces[prefix]+'}'+name
    for prefix, uri in namespaces.items():
        ET.register_namespace(prefix, uri)
    root = ET.fromstring(pdf.Root.Metadata.read_bytes())
    description = root.find('.//'+tag('rdf', 'Description'))
    if description is None:
        return
    def replace(prefix, name):
        key = tag(prefix, name)
        for parent in root.iter(tag('rdf', 'Description')):
            parent.attrib.pop(key, None)
            for child in list(parent):
                if child.tag == key:
                    parent.remove(child)
        return ET.SubElement(description, key)
    def resource(parent):
        parent.set(tag('rdf', 'parseType'), 'Resource')
        return parent
    def value(parent, prefix, name, text):
        ET.SubElement(parent, tag(prefix, name)).text = str(text)
    if drawings:
        size = resource(replace('xmpTPg', 'MaxPageSize'))
        value(size, 'stDim', 'w', max(drawing.box[2]-drawing.box[0] for drawing in drawings))
        value(size, 'stDim', 'h', max(drawing.box[3]-drawing.box[1] for drawing in drawings))
        value(size, 'stDim', 'unit', 'Points')
        spots = {spot.name: spot for drawing in drawings for spot in drawing.spots}
        process_names = []
        for line in meta.splitlines():
            if line.startswith(b'%%DocumentProcessColors:'):
                process_names = line.split(b':', 1)[1].decode('ascii').split()
        plates = ET.SubElement(replace('xmpTPg', 'PlateNames'), tag('rdf', 'Seq'))
        for name in [*process_names, *spots]:
            value(plates, 'rdf', 'li', name)
        groups = ET.SubElement(replace('xmpTPg', 'SwatchGroups'), tag('rdf', 'Seq'))
        group = resource(ET.SubElement(groups, tag('rdf', 'li')))
        value(group, 'xmpG', 'groupName', '初期設定のスウォッチグループ')
        value(group, 'xmpG', 'groupType', 0)
        colors = ET.SubElement(ET.SubElement(group, tag('xmpG', 'Colorants')), tag('rdf', 'Seq'))
        for spot in spots.values():
            color = resource(ET.SubElement(colors, tag('rdf', 'li')))
            value(color, 'xmpG', 'swatchName', spot.name)
            value(color, 'xmpG', 'type', 'SPOT')
            value(color, 'xmpG', 'tint', '100.000000')
            value(color, 'xmpG', 'mode', 'LAB' if spot.lab is not None else 'CMYK')
            keys = ('L', 'A', 'B') if spot.lab is not None else ('cyan', 'magenta', 'yellow', 'black')
            values = spot.lab if spot.lab is not None else tuple(component*100 for component in spot.cmyk)
            for key, component in zip(keys, values):
                value(color, 'xmpG', key, f'{component:.6f}')
    image = document_preview(pdf, artboard_boxes)
    encoded = BytesIO(); image.save(encoded, format='JPEG', quality=75)
    previews = ET.SubElement(replace('xmp', 'Thumbnails'), tag('rdf', 'Alt'))
    preview = resource(ET.SubElement(previews, tag('rdf', 'li')))
    value(preview, 'xmpGImg', 'width', image.width)
    value(preview, 'xmpGImg', 'height', image.height)
    value(preview, 'xmpGImg', 'format', 'JPEG')
    value(preview, 'xmpGImg', 'image', base64.b64encode(encoded.getvalue()).decode('ascii'))
    xml = pdf.make_stream(ET.tostring(root, encoding='utf-8', xml_declaration=True))
    xml.Type = pikepdf.Name.Metadata; xml.Subtype = pikepdf.Name.XML
    pdf.Root.Metadata = xml


def document_preview(pdf, artboard_boxes=None):
    """Adobe's 256px artwork preview, independent of the small PDF thumbnails."""
    import math
    import pymupdf
    from PIL import Image
    buffer = BytesIO()
    pdf.save(buffer)
    with pymupdf.open(stream=buffer.getvalue(), filetype='pdf') as document:
        if artboard_boxes is None:
            page = document[0]
            # Adobe previews artwork rather than surrounding blank paper.
            clip = page.artbox & page.rect
            if clip.is_empty:
                clip = page.rect
            scale = 256/max(clip.width, clip.height)
            pixels = page.get_pixmap(matrix=pymupdf.Matrix(scale,scale), clip=clip,
                                     colorspace=pymupdf.csRGB, alpha=False)
            image = Image.frombytes('RGB',(pixels.width,pixels.height),pixels.samples)
            # Raster rounding at a fractional clip origin can add one pixel.
            image.thumbnail((256,256), Image.Resampling.LANCZOS)
            return image
        x0 = min(box[0] for box in artboard_boxes)
        y0 = min(box[1] for box in artboard_boxes)
        x1 = max(box[2] for box in artboard_boxes)
        y1 = max(box[3] for box in artboard_boxes)
        scale = 256/max(x1-x0,y1-y0)
        image = Image.new('RGB',(max(1,math.ceil((x1-x0)*scale)),
                                 max(1,math.ceil((y1-y0)*scale))), 'white')
        for page,box in zip(document,artboard_boxes):
            pixels = page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),
                                     colorspace=pymupdf.csRGB, alpha=False)
            tile = Image.frombytes('RGB',(pixels.width,pixels.height),pixels.samples)
            image.paste(tile,(round((box[0]-x0)*scale),round((y1-box[3])*scale)))
        return image
