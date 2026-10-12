"""Create a single native AI document with one artboard per PDF page."""
from dataclasses import replace
import math
from pathlib import Path
import tempfile

import pikepdf

from .layers import Layer
from .native import drawing_report, make_private, save_ai
from .document_defaults import align_page_settings
from .path_conflicts import paths_conflict
from .input_preparation import prepare_input
from .vector import (Clip, ConversionError, Drawing, Gradient, GroupBoundary, PaintedPath, Raster,
                     Subpath, compose, read_drawing)


def arrange_pages(drawings):
    """Pack pages into rows within the standard Illustrator canvas."""
    limit, gap = 14400, 20
    area = sum((d.box[2] - d.box[0] + gap) * (d.box[3] - d.box[1] + gap) for d in drawings)
    widths = [d.box[2] - d.box[0] for d in drawings]
    target = min(limit, max(max(widths), math.sqrt(area)))
    try:
        return pack_pages(drawings,target,limit,gap)
    except ConversionError:
        if target>=limit:raise
        # A near-square target can wrap a tall narrow page above a wide page
        # even when both fit side by side on the actual Illustrator canvas.
        return pack_pages(drawings,limit,limit,gap)


def pack_pages(drawings,target,limit,gap):
    boxes = []
    x = y = row_height = 0
    for drawing in drawings:
        w, h = drawing.box[2] - drawing.box[0], drawing.box[3] - drawing.box[1]
        if w > limit or h > limit:
            raise ConversionError('ページがAIキャンバスに収まりません。ページ別出力を選択してください。')
        if x and x + w > target:
            x = 0
            y += row_height + gap
            row_height = 0
        if y + h > limit:
            raise ConversionError('全ページがAIキャンバスに収まりません。対象ページを減らすか、ページ別出力を選択してください。')
        boxes.append((x, y, x + w, y + h))
        x += w + gap
        row_height = max(row_height, h)
    width = max(b[2] for b in boxes)
    height = max(b[3] for b in boxes)
    # Order top to bottom; center the packed artwork on the standard canvas.
    return [(x0-width/2, height/2-y1, x1-width/2, height/2-y0) for x0,y0,x1,y1 in boxes]


def translate_drawing(drawing, box, page):
    dx, dy = box[0] - drawing.box[0], box[1] - drawing.box[1]
    def path(p):
        return replace(p, commands=[(op, tuple(v + (dx if i % 2 == 0 else dy)
                                              for i, v in enumerate(values)))
                                    for op, values in p.commands])
    def clip(c):
        return Clip([path(p) for p in c.paths], c.even_odd)
    layers = {}
    for i, layer in enumerate([None, *drawing.layers]):
        layers[layer] = Layer((page, i), f'ページ {page}' + (f' / {layer.name}' if layer else ''),
                              layer.visible if layer else True, layer.locked if layer else False,
                              layer.printable if layer else True)
    def paint(value):
        if isinstance(value, Gradient):
            return replace(value, name=f'Page {page} / {value.name}',
                           start=(value.start[0]+dx, value.start[1]+dy),
                           end=(value.end[0]+dx, value.end[1]+dy),
                           focus=(value.focus[0]+dx,value.focus[1]+dy) if value.focus is not None else None)
        return value
    items = []
    x0, y0, x1, y1 = box
    page_clip = Clip([Subpath([('m',(x0,y0)), ('L',(x1,y0)),
                              ('L',(x1,y1)), ('L',(x0,y1))], True)], False)
    for item in drawing.items or drawing.paths:
        state = replace(item.state, matrix=compose((1,0,0,1,dx,dy), item.state.matrix),
                        fill=paint(item.state.fill), stroke=paint(item.state.stroke),
                        clips=(page_clip, *(clip(c) for c in item.state.clips)), layer=layers[item.state.layer])
        if isinstance(item, PaintedPath):
            items.append(replace(item, paths=[path(p) for p in item.paths], state=state))
        else:
            items.append(replace(item, state=state))
    return replace(drawing, box=box, items=items,
                   paths=[i for i in items if isinstance(i, PaintedPath)],
                   images=[i for i in items if isinstance(i, Raster)],
                   layers=[layers[l] for l in drawing.layers])


@prepare_input
def convert_document(source, output, *, page_labels=None, pages=None, overwrite=False,
                     raster_fallback=True, raster_dpi=300, progress=None, outline_text=False, ghostscript=None,
                     inspection_only=False):
    """Convert all pages atomically; a failed page prevents publishing the AI."""
    source = Path(source)
    output = Path(tempfile.gettempdir())/'pdf2ai-inspection.ai' if inspection_only else Path(output)
    if paths_conflict(source, output):
        raise ConversionError('Input and output must differ')
    if output.suffix.lower() != '.ai' or not output.parent.is_dir():
        raise ConversionError('出力先フォルダーと .ai 拡張子を確認してください。')
    if not inspection_only and output.exists() and not overwrite:
        raise FileExistsError(f'出力が既に存在します: {output.name}')
    if not inspection_only and output.is_dir():raise ConversionError('Output must be a file, not a directory')
    if not math.isfinite(raster_dpi) or not 72 <= raster_dpi <= 1200:
        raise ConversionError('Raster DPI must be between 72 and 1200')
    with pikepdf.open(source) as pdf:
        if pdf.is_encrypted:
            raise ConversionError('Encrypted PDFs are unsupported')
        selected = list(pages) if pages is not None else list(range(1, len(pdf.pages)+1))
        if not selected or any(type(p) is not int or not 1 <= p <= len(pdf.pages) for p in selected) or len(set(selected)) != len(selected):
            raise ConversionError('Invalid page selection')
        if not 1 <= len(selected) <= 1000:
            raise ConversionError('1つのAIにまとめられるページ数は1〜1000です。')
        labels = list(page_labels) if page_labels is not None else selected
        if len(labels) != len(selected) or any(type(p) is not int or p < 1 for p in labels) or len(set(labels)) != len(labels):
            raise ConversionError('Invalid page selection')
        from .dic import normalize_pdf_spots
        # Normalize all selected pages before rendering any fallback page, since
        # pages can share indirect color-space dictionaries and Form resources.
        normalized_dic = {number: normalize_pdf_spots(pdf.pages[number-1]) for number in selected}
        from .toyo import normalize_pdf_spots as normalize_toyo
        normalized_toyo = {number: normalize_toyo(pdf.pages[number-1]) for number in selected}
        from .image_resources import normalize_image_spaces
        normalized_images = {number: normalize_image_spaces(pdf.pages[number-1],pdf) for number in selected}
        outlined_pdf = None
        outline_directory = None
        if outline_text:
            if pdf.Root.get('/OCProperties') is not None:
                raise ConversionError('Text outlining with PDF layers is unsupported; use an already outlined layered PDF')
            from .preprocess import outline_pdf
            # Keep the PDF and its temporary storage alive throughout parsing.
            outline_directory = tempfile.TemporaryDirectory(prefix='pdf2ai-outline-', dir=output.parent)
            try:
                outlined = Path(outline_directory.name)/'outlined.pdf'
                outline_pdf(source, outlined, ghostscript)
                outlined_pdf = pikepdf.open(outlined)
                if len(outlined_pdf.pages) != len(pdf.pages):
                    raise ConversionError('Text outlining changed the page count')
            except BaseException:
                if outlined_pdf is not None: outlined_pdf.close()
                outline_directory.cleanup()
                raise
        try:
            return _finish_document(pdf, source, output, selected, labels, normalized_dic, normalized_toyo, normalized_images,
                raster_fallback, raster_dpi, progress, overwrite, outline_text, outlined_pdf,
                inspection_only)
        finally:
            if outlined_pdf is not None: outlined_pdf.close()
            if outline_directory is not None: outline_directory.cleanup()


def _finish_document(pdf, source, output, selected, labels, normalized_dic, normalized_toyo, normalized_images,
                     raster_fallback, raster_dpi, progress, overwrite, outline_text,
                     outlined_pdf, inspection_only):
    from contextlib import ExitStack
    with ExitStack() as stack:
        normalized_source = None
        def render_source():
            nonlocal normalized_source
            if not any(normalized_dic.values()) and not any(normalized_toyo.values()) and not any(normalized_images.values()): return source
            if normalized_source is None:
                directory = stack.enter_context(tempfile.TemporaryDirectory(prefix='pdf2ai-spots-',dir=output.parent))
                normalized_source = Path(directory)/'normalized.pdf'
                pdf.save(normalized_source)
            return normalized_source
        return _assemble_document(pdf, source, output, selected, labels, normalized_dic, normalized_toyo,
            raster_fallback, raster_dpi, progress, overwrite, outline_text, outlined_pdf,
            inspection_only, render_source)


def _assemble_document(pdf, source, output, selected, labels, normalized_dic, normalized_toyo,
                       raster_fallback, raster_dpi, progress, overwrite, outline_text,
                       outlined_pdf, inspection_only, render_source):
    drawings, reports = [], []
    for index, number in enumerate(selected):
        page = pdf.pages[number-1]
        reason = None
        try:
            drawing = read_drawing(outlined_pdf.pages[number-1], root=outlined_pdf.Root) if outlined_pdf is not None else read_drawing(page, root=pdf.Root)
            make_private(drawing, source.name)  # Validate native serialization, too.
        except (ConversionError, pikepdf.PdfError, NotImplementedError) as error:
            if not raster_fallback:
                raise ConversionError(f'ページ{labels[index]}：{error}') from error
            from .rasterize import render_drawing
            reason = str(error)
            drawing = render_drawing(render_source(), number-1, raster_dpi)
        if normalized_dic[number]:
            drawing.color_conversions.append('DIC spot alternate colors normalized to legacy CMYK book: '+', '.join(normalized_dic[number]))
        if normalized_toyo[number]:
            drawing.color_conversions.append('TOYO spot names and CMYK alternates normalized using independent Lab book: '+', '.join(normalized_toyo[number]))
        drawings.append(drawing)
        report = drawing_report(drawing, source, output, number-1,
                                'raster-fallback' if reason else 'vector', reason, raster_dpi, outline_text, 0)
        report['page'] = labels[index]
        reports.append(report)
        if progress is not None:progress(labels[index],index+1,len(selected))
    boxes = arrange_pages(drawings)
    shifted = [translate_drawing(d, b, p) for d, b, p in zip(drawings, boxes, labels)]
    combined_model = 'RGB' if any(d.color_model == 'RGB' for d in shifted) else 'CMYK'
    for drawing,report in zip(shifted,reports):
        if any(isinstance(i,GroupBoundary) and i.color_model is not None and i.color_model != combined_model
               for i in drawing.items):
            raise ConversionError(f"ページ{report['page']}の透明グループ色空間が結合AIと異なります。ページ別出力を選択してください。")
        # Choosing an RGB document at merge time also changes the image
        # destination space, even if the individual page was CMYK.
        if combined_model == 'RGB':
            from .color_management import cmyk_to_rgb
            for image in drawing.images:
                if image.model == 'CMYK':
                    image.pixels = cmyk_to_rgb(image.pixels,image.width,image.height)
                    image.model = 'RGB'
                    report['color_conversions'] = [*report['color_conversions'],
                        'DeviceCMYK image normalized to PDF renderer RGB for combined AI']
        report['combined_color_model'] = combined_model
    spots = {}
    for drawing in shifted:
        for spot in drawing.spots:
            if spot.name in spots and spots[spot.name] != spot:
                raise ConversionError(f'ページ間で特色「{spot.name}」の定義が異なります。ページ別出力を選択してください。')
            spots[spot.name] = spot
    merged = Drawing((min(b[0] for b in boxes), min(b[1] for b in boxes),
                      max(b[2] for b in boxes), max(b[3] for b in boxes)),
                     [p for d in shifted for p in d.paths], list(spots.values()), {},
                     images=[i for d in shifted for i in d.images],
                     items=[i for d in shifted for i in d.items],
                     color_model=combined_model,
                     layers=[l for d in shifted for l in d.layers])
    artboards = [(f'Page {p}', box) for p, box in zip(labels, boxes)]
    meta, private = make_private(merged, source.name, artboards=artboards)
    if inspection_only:
        for report, box in zip(reports, boxes):
            report.update(inspection_only=True, native_supported=not report['rasterized'],
                          planned_mode=report['conversion_mode'], all_blockers_enumerated=False,
                          combined_constraints_checked=True, artboard_box=list(box), output='')
            if report['rasterized']: report['first_blocker'] = report['fallback_reason']
        return reports
    # Preserve the requested order in the PDF representation as well.
    original_pages = list(pdf.pages)
    for number in selected:
        pdf.pages.append(original_pages[number-1])
    for _ in original_pages:
        del pdf.pages[0]
    for page, drawing in zip(pdf.pages, drawings):
        align_page_settings(page, drawing)
    blocks = save_ai(pdf, output, meta, private, overwrite=overwrite, drawings=drawings, artboard_boxes=boxes)
    for report, box in zip(reports, boxes):
        report.update(private_blocks=blocks, artboard_box=list(box))
    return reports
