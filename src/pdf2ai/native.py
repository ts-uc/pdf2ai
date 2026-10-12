"""Generate Illustrator 24 editing streams and PDF containers."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import tempfile
import os
import uuid
import zlib
from dataclasses import replace

import pikepdf
from PIL import Image
from fontTools.pens.boundsPen import BoundsPen

from .codec import MARKER, compress, decode_private
from .path_conflicts import paths_conflict
from .input_preparation import prepare_input
from .document_defaults import (fill_artwork_bounds, align_page_settings, add_page_thumbnails,
                                set_document_metadata, set_structured_metadata)
from .vector import Color, ConversionError, Drawing, Gradient, Raster, Clip, Subpath, PaintedPath, GroupBoundary, BLEND_MODES, STROKE_CURVE_FLATNESS, read_drawing


AI_CREATOR = "Adobe Illustrator 24.0 (Macintosh)"
AI_PRODUCER = "Adobe PDF library 15.00"


def num(value: float) -> str:
    if not math.isfinite(value): raise ConversionError("Nonfinite path coordinate")
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def ps_string(text: str) -> str:
    # AI24 stores Unicode names as UTF-8, escaping only PS syntax and controls.
    return "(" + "".join(char if ord(char) >= 32 and ord(char) != 127 and char not in '()\\'
                         else ''.join(f"\\{b:03o}" for b in char.encode('utf-8'))
                         for char in text) + ")"


def color_command(color: Color, stroke: bool = False) -> str:
    suffix = {"CMYK": "K" if stroke else "k", "RGB": "XA" if stroke else "Xa",
              "Gray": "G" if stroke else "g", "Spot": "X" if stroke else "x"}[color.model]
    if color.spot:
        # Illustrator's custom-color gray is 0 for solid ink, 1 for paper white.
        if color.spot.lab is not None:
            return " ".join(num(v) for v in (*color.spot.cmyk,*color.spot.lab)) + " " + ps_string(color.spot.name) + " " + num(1-color.values[0]) + " 2 " + ("XX" if stroke else "Xx")
        return " ".join(num(v) for v in color.spot.cmyk) + " " + ps_string(color.spot.name) + " " + num(1-color.values[0]) + " " + suffix
    if color.model == 'RGB':
        r,g,b = color.values
        black = 1-max(r,g,b)
        fallback = (0,0,0,1) if black == 1 else ((1-r-black)/(1-black),(1-g-black)/(1-black),(1-b-black)/(1-black),black)
        return ' '.join(num(v) for v in (*fallback,r,g,b))+' '+suffix
    return " ".join(num(v) for v in color.values) + " " + suffix


def path_commands(path):
    commands = path.commands
    # Native AI closed geometry explicitly repeats the anchor at the beginning.
    # Without it, Illustrator may interpret the last edge as a curved segment.
    if path.closed and commands and commands[-1][1][-2:] != commands[0][1]:
        return [*commands, ('L', commands[0][1])]
    return commands


def axial_geometry(item, gradient):
    """Normalize the PDF ramp to Illustrator's projected geometric bounds."""
    pen = BoundsPen(None)
    for path in item.paths:
        for op, values in path.commands:
            if op == 'm': pen.moveTo(values)
            elif op in ('L','l'): pen.lineTo(values)
            elif op in ('C','c'): pen.curveTo(values[:2],values[2:4],values[4:])
            else: raise ConversionError(f'Unsupported gradient path command: {op}')
        if path.closed: pen.closePath()
        else: pen.endPath()
    if pen.bounds is None: raise ConversionError('Empty gradient geometry')
    x0,y0,x1,y1 = pen.bounds
    dx,dy = gradient.end[0]-gradient.start[0],gradient.end[1]-gradient.start[1]
    length = math.hypot(dx,dy)
    if length<1e-10: raise ConversionError('Degenerate gradient vector')
    ux,uy = dx/length,dy/length
    projections = [x*ux+y*uy for x,y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
    first,last = min(projections),max(projections)
    span = last-first
    if span<1e-10: raise ConversionError('Degenerate gradient carrier')
    offset = (gradient.start[0]*ux+gradient.start[1]*uy-first)/span
    return offset, math.degrees(math.atan2(dy,dx)), length/span


def native_items(drawing):
    for item in drawing.items or drawing.paths:
        if isinstance(item,PaintedPath) and item.paint=='fill' and isinstance(item.state.fill,Gradient) and item.state.fill.radial:
            gradient = item.state.fill
            x,y = gradient.start
            radius = math.dist(gradient.start,gradient.end)
            def rectangle(bounds):
                x0,y0,x1,y1 = bounds
                return Subpath([('m',(x0,y0)),('L',(x1,y0)),('L',(x1,y1)),('L',(x0,y1))],True)
            square = rectangle((x-radius,y-radius,x+radius,y+radius))
            # Illustrator reconstructs radial geometry from the fill's bounds.
            # Use an explicitly sized gradient carrier clipped to the original
            # artwork; paint the extended end color only outside that carrier.
            exterior = Clip([rectangle(drawing.box),square],True)
            outside_state = replace(item.state,fill=gradient.stops[-1][1],clips=(*item.state.clips,exterior))
            yield replace(item,state=outside_state)
            inside_state = replace(item.state,clips=(*item.state.clips,Clip(item.paths,item.even_odd)))
            yield replace(item,paths=[square],state=inside_state,even_odd=False)
        else:
            yield item


def layer_runs(drawing):
    """Keep PDF paint order; split a layer only when its artwork is interleaved."""
    runs = []
    for item in native_items(drawing):
        layer = item.state.layer
        if not runs or runs[-1][0]!=layer: runs.append((layer,[]))
        runs[-1][1].append(item)
    present = {layer for layer,_ in runs}
    runs.extend((layer,[]) for layer in drawing.layers if layer not in present)
    if not runs: runs = [(None,[])]
    counts = {}
    result = []
    for layer,items in runs:
        name = layer.name if layer is not None else 'レイヤー 1'
        counts[name] = counts.get(name,0)+1
        if counts[name]>1: name += f' ({counts[name]})'
        result.append((layer,name,items))
    return result


def make_private(drawing: Drawing, title: str, *, artboards=None) -> tuple[bytes, bytes]:
    runs = layer_runs(drawing)
    x0,y0,x1,y1 = drawing.box
    box = " ".join(num(v) for v in drawing.box)
    bx0, by0, bx1, by1 = fill_artwork_bounds(drawing) or drawing.box
    artwork_box = ' '.join(num(value) for value in (bx0, by0, bx1, by1))
    process_inks = set()
    def record_inks(color):
        if isinstance(color, Gradient):
            for _, stop in color.stops:
                record_inks(stop)
        elif color.model == 'CMYK':
            process_inks.update(name for name, value in zip(('Cyan', 'Magenta', 'Yellow', 'Black'), color.values) if value)
        elif color.model == 'Gray' and color.values[0] != 1:
            process_inks.add('Black')
        elif color.model == 'RGB':
            process_inks.update(('Cyan', 'Magenta', 'Yellow', 'Black'))
    for item in drawing.items or drawing.paths:
        if isinstance(item, PaintedPath):
            if item.paint != 'stroke': record_inks(item.state.fill)
            if item.paint != 'fill': record_inks(item.state.stroke)
        elif isinstance(item, Raster):
            process_inks.update(('Cyan', 'Magenta', 'Yellow', 'Black'))
    process_colors = ' '.join(name for name in ('Cyan', 'Magenta', 'Yellow', 'Black') if name in process_inks)
    header = ["%!PS-Adobe-3.0 ", "%%Creator: Adobe Illustrator(R) 24.0",
              "%%AI8_CreatorVersion: 24.0.0", f"%%Title: {ps_string(title)}",
              '%%CreationDate: '+datetime.now(timezone.utc).strftime('%Y/%m/%d %H:%M'),
              "%%Canvassize: 16383", f"%%BoundingBox: {math.floor(bx0)} {math.floor(by0)} {math.ceil(bx1)} {math.ceil(by1)}",
              f"%%HiResBoundingBox: {artwork_box}", '%%DocumentProcessColors:'+(' '+process_colors if process_colors else ''),
              "%AI5_FileFormat 14.0", "%AI12_BuildNumber: 0", "%AI3_ColorUsage: Color",
              "%AI7_ImageSettings: 0", f"%AI3_Cropmarks: {box}", "%AI3_DocumentPreview: None",
              "%AI5_ArtSize: 14400 14400", "%AI5_RulerUnits: 2", "%AI24_LargeCanvasScale: 1",
              f"%AI9_ColorModel: {1 if drawing.color_model == 'RGB' else 2}", "%AI5_ArtFlags: 0 0 0 1 0 0 1 0 0",
              "%AI5_TargetResolution: 800", f"%AI5_NumLayers: {len(runs)}"]
    if drawing.spots:
        header += ["%%DocumentCustomColors: " + ps_string(drawing.spots[0].name)]
        header += ["%%+ " + ps_string(spot.name) for spot in drawing.spots[1:]]
        for i,spot in enumerate(drawing.spots):
            header.append(("%%CMYKCustomColor: " if i == 0 else "%%+ ") +
                          " ".join(num(v) for v in spot.cmyk) + " " + ps_string(spot.name))
    header += ['%%CMYKProcessColor: 1 1 1 1 '+ps_string('[レジストレーション]'), "%%EndComments"]
    # Adobe places plate declarations before the page/document settings.
    settings = next(i for i,line in enumerate(header) if line.startswith('%AI3_Cropmarks:'))
    plates = next(i for i,line in enumerate(header) if line.startswith(('%%DocumentCustomColors:', '%%CMYKProcessColor:')))
    header = header[:settings] + header[plates:-1] + header[settings:plates] + header[-1:]
    gradients = list(dict.fromkeys(item.state.fill for item in drawing.paths
                                   if item.paint != 'stroke' and isinstance(item.state.fill, Gradient)))
    body = ["%%BeginProlog", "%%EndProlog", "%%BeginSetup",
            '%AI5_Begin_NonPrinting', 'Np', '%AI9_BeginArtStyles', '/KnownStyle :',
            ps_string('[デフォルト]')+' /Name ,', '/SimpleStyle :', '0 O', '0 0 0 0 k',
            '0 R', '0 0 0 1 K', '0 1 0 0 0 Xy', '0 J 0 j 1 w 10 M []0 d',
            '0 XR', '1 1 Xd', '/Paint ;', ' /Def ;', '%AI9_EndArtStyles', '%AI5_End_NonPrinting--',
            "%AI5_BeginPalette", "0 0 Pb", '1 1 1 1 '+ps_string('[レジストレーション]')+' 0 Xs',
            ps_string('[レジストレーション]'), 'Pc']
    for spot in drawing.spots:
        body += [color_command(Color('Spot',(1,),spot)),
                 ps_string(spot.name), "Pc"]
    body += ["PB", "%AI5_EndPalette",
             '%AI5_Begin_NonPrinting', 'Np', '%AI9_BeginArtStyleList',
             ps_string('[デフォルト]'), '%AI9_EndArtStyleList', '%AI5_End_NonPrinting--',
             '%AI5_Begin_NonPrinting', 'Np', '%AI24_BeginSymbolList',
             '%AI24_EndSymbolList', '%AI5_End_NonPrinting--', f"{len(gradients)} Bn"]
    for gradient in gradients:
        body += [f"%AI5_BeginGradient: {ps_string(gradient.name)}",
                 f"{ps_string(gradient.name)} {int(gradient.radial)} {len(gradient.stops)} Bd", "["]
        for position,color in (gradient.stops if gradient.radial else reversed(gradient.stops)):
            # A gray ramp in an RGB document is otherwise interpolated using
            # Illustrator's working-gray tone curve, unlike PDF DeviceGray.
            if color.model == 'Gray' and drawing.color_model == 'RGB':
                color = Color('RGB', color.values * 3)
            command = color_command(color).rsplit(' ',1)[0]
            style = {'Gray':0,'CMYK':1,'RGB':2}[color.model]
            body.append(f"{command} {style} 1 6 50 {num(position*100)} %_BS")
            body.append(f"%_{command} {style} 1 6 50 {num(position*100)} Bs")
        body += ['BD','%AI5_EndGradient']
    body += ["%AI9_BeginDocumentData",
             "%_/Document :", "%_/Dictionary :", "%_16383 /Int (AIDocumentCanvasSize) ,",
             "%_/Array :"]
    for name, (ax0, ay0, ax1, ay1) in artboards or [('アートボード 1', drawing.box)]:
        body += ["%_/Dictionary :", f"%_{int(artboards is None)} /Bool (IsArtboardDefaultName) ,",
             "%_0 /Bool (IsArtboardSelected) ,", "%_0 /Bool (IsArtboardLocked) ,",
             "%_/FillStyle : 0 1 0 0 0 Xy", "%_0 J 0 j 1 w 10 M []0 d",
             "%_0 XR", "%_0 0 Xd", "%_/Def ;", "%_ (EachArtboardColor) ,",
             "%_8191 8191 /RealPoint", "%_ (RulerOrigin) ,",
             f"%_{num(ax0)} {num(ay1)} /RealPointRelToROrigin", "%_ (PositionPoint1) ,",
             f"%_{num(ax1)} {num(ay0)} /RealPointRelToROrigin", "%_ (PositionPoint2) ,",
             "%_1 /Real (PAR) ,", "%_0 /Int (DisplayMark) ,",
             f"%_{ps_string(name)} /UnicodeString (Name) ,",
             f"%_{ps_string(str(uuid.uuid4()))} /String (ArtboardUUID) ,",
             "%_; ,"]
    body += ["%_; (ArtboardArray) ,", "%_0 /Int (CropAreaActive) ,",
             "%_; /Recorded ,", "%_/Dictionary : /NotRecorded ,",
             "%_; /NotRecorded ,", "%_;", "%AI9_EndDocumentData", "%%EndSetup"]
    layer_boundaries = {}
    all_items = []
    for layer,name,items in runs:
        visible,enabled,printing = (int(layer.visible),int(not layer.locked),int(layer.printable)) if layer is not None else (1,1,1)
        layer_boundaries[len(all_items)] = layer_boundaries.get(len(all_items),[]) + [
            '%AI5_BeginLayer',f'{visible} 1 {enabled} {printing} 0 0 1 0 79 128 255 0 50 0 Lb',ps_string(name)+' Ln','0 AE']
        if items:
            all_items.extend(items)
            layer_boundaries[len(all_items)] = ['LB','%AI5_EndLayer--']
        else:
            layer_boundaries[len(all_items)] += ['LB','%AI5_EndLayer--']
    for index,item in enumerate(all_items):
        body += layer_boundaries.get(index,[])
        state = item.state
        if isinstance(item,GroupBoundary):
            if item.begin:
                body += ['u']
            else:
                body += ['U',f'{BLEND_MODES[state.blend_mode]} {num(state.fill_alpha)} {int(item.isolated)} {1 if item.knockout else 2} 0 Xy',
                         '0 0 Xd','6 () XW']
            continue
        for clip in state.clips:
            body += ['q',f'{int(clip.even_odd)} XR']
            if len(clip.paths)>1: body.append('*u')
            for path in clip.paths:
                for op,coords in path_commands(path):
                    body.append(' '.join(num(v) for v in coords)+' '+op)
                body += ['h','W','n']
            if len(clip.paths)>1: body.append('*U')
        body += ["0 A", "0 Xw", "0 Ae"]
        blend = BLEND_MODES[state.blend_mode]
        if isinstance(item,Raster):
            w,h = item.width,item.height
            a,b,c,d,e,f = state.matrix
            matrix = ' '.join(num(v) for v in (a/w,b/w,c/h,d/h,e+c,f+d))
            # Illustrator XI does not reliably accept the one-channel gray
            # representation. Expand gray pixels without changing their values.
            model = 'RGB' if item.model == 'Gray' else item.model
            pixels = Image.frombytes('L',(w,h),item.pixels).convert('RGB').tobytes() if item.model == 'Gray' else item.pixels
            # The XI flags used here require an alpha plane even for opaque
            # images; otherwise Illustrator reads following stream bytes as alpha.
            alpha = item.alpha if item.alpha is not None else bytes([255])*(w*h)
            image_type = {'RGB':3,'CMYK':4}[model]
            channels = {'RGB':3,'CMYK':4}[model]
            total_channels = channels + 1
            space = {'RGB':'DeviceRGB','CMYK':'DeviceCMYK'}[model]
            raster_flags = 18 if model == 'CMYK' else 17
            body += ['1 Ap',f'{blend} {num(state.fill_alpha)} 0 0 0 Xy',
                     '%AI5_BeginRaster','() 1 XG',f'/{space} XN',
                     f'[ {matrix} ] {w} {h} 0 Xh',
                     f'[ {matrix} ] 0 0 {w} {h} {w} {h} 8 {image_type} 1 {raster_flags} 1 0 {total_channels} {total_channels} 0 0',
                     f'%%BeginData: {len(pixels)+len(alpha)+3}',
                     b'XI\n'+pixels+alpha,
                     '%%EndData','XH','%AI5_EndRaster','N']
            body += ['Q']*len(state.clips)
            continue
        if len(item.paths)>1: body.append("*u")
        if item.paint != "stroke":
            body += [f"{int(state.fill_overprint)} O"]
            if not isinstance(state.fill, Gradient): body.append(color_command(state.fill))
        if item.paint != "fill":
            body += [f"{int(state.stroke_overprint)} R", color_command(state.stroke,True)]
        opacity = state.stroke_alpha if item.paint == 'stroke' else state.fill_alpha
        flags = f"{blend} {num(opacity)} 0 0 0 Xy"
        # A zero PDF line width has no effect on fill-only artwork. Illustrator's
        # unused stroke style can use a normal width without changing its appearance.
        width = 1 if item.paint == "fill" and state.width == 0 else state.width*item.stroke_scale
        body += [flags, f"{state.cap} J {state.join} j {num(width)} w {num(state.miter)} M",
                 "["+" ".join(num(v*item.stroke_scale) for v in state.dash)+"] "+num(state.phase*item.stroke_scale)+" d",
                 f"{int(item.even_odd)} XR"]
        # Illustrator reverses compound children when exporting its PDF view.
        # Reverse the native solid-fill children so that the exported PDF keeps
        # the input's subpath order and the same decimal-rounding origin.
        # Coordinates, winding, and the Drawing itself remain untouched.
        paths = (reversed(item.paths) if item.paint == 'fill' and len(item.paths)>1
                 and isinstance(state.fill,Color) and state.fill_alpha == 1
                 and state.blend_mode == 'Normal' else item.paths)
        for path in paths:
            body.append(f"{max(0,len(path_commands(path))-1)} As")
            for op,coords in path_commands(path):
                body.append(" ".join(num(v) for v in coords)+" "+op)
            if item.paint != 'stroke' and isinstance(state.fill, Gradient):
                gradient = state.fill
                x,y = gradient.start
                dx,dy = gradient.end[0]-x,gradient.end[1]-y
                body.append('Bb')
                if gradient.radial:
                    if gradient.focus is None:
                        body.append('0 0 0 0 Bh')
                    else:
                        fx,fy = gradient.focus[0]-x,gradient.focus[1]-y
                        body.append(f'0 0 {num(math.degrees(math.atan2(fy,fx)))} {num(math.hypot(fx,fy)/math.hypot(dx,dy))} Bh')
                # CC2020's final Bg flag selects normalized geometry. Xm/Bm
                # cannot substitute for its ramp offset and length.
                offset,angle,length = (0,0,1) if gradient.radial else axial_geometry(item,gradient)
                body.append(f'1 {ps_string(gradient.name)} {num(offset)} 0 {num(angle)} {num(length)} 1 0 0 1 0 0 1 Bg')
                if not gradient.radial:
                    body.append(f'{num(dx)} {num(dy)} {num(dy)} {num(-dx)} {num(x)} {num(y)} Xm')
                body.append(f'{num(dx)} {num(dy)} {num(dy)} {num(-dx)} {num(x)} {num(y)} Bm')
            terminal = {"fill":"F", "stroke":"S", "both":"B"}[item.paint]
            body.append(terminal.lower() if path.closed else terminal)
            if item.paint != 'stroke' and isinstance(state.fill, Gradient): body.append('0 BB')
        if len(item.paths)>1: body.append("*U")
        body += ['Q']*len(state.clips)
    body += layer_boundaries.get(len(all_items),[])
    body += ["%%PageTrailer", "gsave annotatepage grestore showpage", "%%Trailer", "%%EOF"]
    meta = ("\r".join(header)+"\r").encode("utf-8")
    return meta, meta+b'\r'.join(part.encode('utf-8') if isinstance(part,str) else part for part in body)+b'\r'


def read_private(pdf) -> bytes | None:
    for page in pdf.pages:
        private = page.obj.get("/PieceInfo", {}).get("/Illustrator", {}).get("/Private")
        if private is not None:
            keys = sorted((k for k in private if str(k).startswith("/AIPrivateData")),
                          key=lambda k:int(str(k)[len('/AIPrivateData'):]))
            if keys: return decode_private(b"".join(private[k].read_bytes() for k in keys))
    return None


@prepare_input
def convert(source: Path | str, output: Path | str, *, page_number: int | None = None,
            overwrite: bool = False, outline_text: bool = False, ghostscript: str | None = None, raster_fallback: bool = True, raster_dpi: float = 300) -> dict:
    source,output = Path(source),Path(output)
    if paths_conflict(source, output): raise ConversionError("Input and output must differ")
    if output.suffix.lower() != ".ai": raise ConversionError("Output must have an .ai extension")
    if output.exists() and not overwrite: raise ConversionError(f"Output already exists: {output}")
    if not output.parent.is_dir(): raise ConversionError(f"Output directory does not exist: {output.parent}")
    if output.is_dir():raise ConversionError('Output must be a file, not a directory')
    if page_number is not None and (type(page_number) is not int or page_number < 1):
        raise ConversionError('Page number must be a positive integer')
    if not math.isfinite(raster_dpi) or not 72<=raster_dpi<=1200:
        raise ConversionError("Raster DPI must be between 72 and 1200")
    with pikepdf.open(source) as pdf:
        if pdf.is_encrypted: raise ConversionError("Encrypted PDFs are unsupported")
        if not len(pdf.pages):raise ConversionError('PDF has no pages')
        if len(pdf.pages) != 1 and page_number is None:
            raise ConversionError("Multipage PDF: specify --page N; one page per AI file")
        index = (1 if page_number is None else page_number)-1
        if not 0 <= index < len(pdf.pages): raise ConversionError("Page number is out of range")
        page = pdf.pages[index]
        from .dic import normalize_pdf_spots
        normalized_dic = normalize_pdf_spots(page)
        from .toyo import normalize_pdf_spots as normalize_toyo
        normalized_toyo = normalize_toyo(page)
        from .image_resources import normalize_image_spaces
        normalized_images = normalize_image_spaces(page,pdf)
        fallback_reason = None
        conversion_mode = 'vector'
        try:
            if outline_text:
                if pdf.Root.get("/OCProperties") is not None:
                    raise ConversionError("Text outlining with PDF layers is unsupported; use an already outlined layered PDF")
                from .preprocess import outline_pdf
                with tempfile.TemporaryDirectory(prefix='pdf2ai-outline-',dir=output.parent) as directory:
                    outlined = Path(directory)/'outlined.pdf'
                    outline_pdf(source,outlined,ghostscript)
                    with pikepdf.open(outlined) as outlined_pdf:
                        if len(outlined_pdf.pages)!=len(pdf.pages): raise ConversionError("Text outlining changed the page count")
                        drawing = read_drawing(outlined_pdf.pages[index],root=outlined_pdf.Root)
                # Keep the original PDF representation/resources; only the editable AI
                # artwork comes from the outlined document.
            else:
                drawing = read_drawing(page,root=pdf.Root)  # Finish validation before creating any output.
            meta,private = make_private(drawing, source.name)
        except (ConversionError,pikepdf.PdfError,NotImplementedError) as exc:
            if not raster_fallback: raise
            from .rasterize import render_drawing
            fallback_reason = str(exc)
            if normalized_dic or normalized_toyo or normalized_images:
                with tempfile.TemporaryDirectory(prefix='pdf2ai-dic-', dir=output.parent) as directory:
                    normalized = Path(directory)/'normalized.pdf'
                    pdf.save(normalized)
                    drawing = render_drawing(normalized,index,raster_dpi)
            else:
                drawing = render_drawing(source,index,raster_dpi)
            conversion_mode = 'raster-fallback'
            meta,private = make_private(drawing, source.name)
        if normalized_dic:
            drawing.color_conversions.append('DIC spot alternate colors normalized to legacy CMYK book: '+', '.join(normalized_dic))
        if normalized_toyo:
            drawing.color_conversions.append('TOYO spot alternate colors normalized to independent Lab book: '+', '.join(normalized_toyo))
        # Remove pages in reverse order so page dictionaries/resources remain owned
        # by this PDF, including OutputIntents and embedded color profiles.
        for i in range(len(pdf.pages)-1,-1,-1):
            if i != index: del pdf.pages[i]
        page = pdf.pages[0]
        align_page_settings(page, drawing)
        private_blocks = save_ai(pdf, output, meta, private, overwrite=overwrite, drawings=[drawing])
    return drawing_report(drawing, source, output, index, conversion_mode, fallback_reason, raster_dpi, outline_text, private_blocks)


def save_ai(pdf, output, meta, private, *, overwrite=False, drawings=None, artboard_boxes=None):
    """Attach one shared editing stream to every PDF page and publish atomically."""
    page = pdf.pages[0]
    compressed = MARKER+compress(private)
    chunks = [compressed[i:i+65536] for i in range(0,len(compressed),65536)]
    dictionary = pikepdf.Dictionary(ContainerVersion=12, CreatorVersion=24,
                                    RoundtripVersion=24, RoundtripStreamType=2,
                                    AIMetaData=pdf.make_stream(meta))
    if len(chunks)>1: dictionary.NumBlock = len(chunks)
    for i,chunk in enumerate(chunks,1): dictionary[f"/AIPrivateData{i}"] = pdf.make_stream(chunk)
    moment = datetime.now(timezone.utc)
    timestamp = moment.strftime("D:%Y%m%d%H%M%SZ")
    piece = page.obj.get("/PieceInfo", pikepdf.Dictionary())
    piece.Illustrator = pikepdf.Dictionary(LastModified=pikepdf.String(timestamp),Private=dictionary)
    shared_piece = pdf.make_indirect(piece)
    for page in pdf.pages:
        page.obj.PieceInfo = shared_piece
    pdf.docinfo["/Creator"] = AI_CREATOR
    pdf.docinfo["/Producer"] = AI_PRODUCER
    set_document_metadata(pdf, output, moment, drawings)
    if drawings is not None:
        from .pdf_groups import explicit_page_knockout
        for page,drawing in zip(pdf.pages,drawings):
            # Apply only to supported native page groups, never to fallback data.
            if drawing.items and isinstance(drawing.items[0],GroupBoundary) and drawing.items[0].knockout:
                explicit_page_knockout(pdf,page)
    add_page_thumbnails(pdf)
    # Do not claim PDF/X certification for a newly written file without preflight.
    for key in ("/GTS_PDFXVersion", "/GTS_PDFXConformance"):
        if key in pdf.docinfo: del pdf.docinfo[key]
    with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
        metadata["xmp:CreatorTool"] = AI_CREATOR
        metadata["pdf:Producer"] = AI_PRODUCER
        for key in ("pdfxid:GTS_PDFXVersion", "pdfx:GTS_PDFXVersion", "pdfx:GTS_PDFXConformance"):
            if key in metadata: del metadata[key]
    set_structured_metadata(pdf, drawings, meta, artboard_boxes=artboard_boxes)
    # Adobe leaves its Zstandard blocks and AIMetaData unfiltered. Applying
    # Flate to already compressed blocks adds a second, unnecessary wrapper.
    unfiltered = {dictionary.AIMetaData.objgen, pdf.Root.Metadata.objgen}
    unfiltered.update(dictionary[f'/AIPrivateData{i}'].objgen for i in range(1,len(chunks)+1))
    for obj in pdf.objects:
        if isinstance(obj,pikepdf.Stream) and '/Filter' not in obj and obj.objgen not in unfiltered:
            obj.write(zlib.compress(obj.read_bytes()), filter=pikepdf.Name.FlateDecode)
    fd,temporary = tempfile.mkstemp(prefix=".pdf2ai-",suffix=".ai",dir=output.parent)
    os.close(fd)
    try:
        pdf.save(temporary, min_version="1.6", compress_streams=False)
        with pikepdf.open(temporary) as check:
            if read_private(check) != private: raise ConversionError("Private-stream verification failed")
        # Hard-link publication fails atomically if an output appeared during
        # conversion. Windows, macOS and Linux support same-directory links.
        if overwrite: os.replace(temporary,output)
        else:
            os.link(temporary,output)
            os.unlink(temporary)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return len(chunks)


def drawing_report(drawing, source, output, index, conversion_mode, fallback_reason, raster_dpi, outline_text, private_blocks):
    warnings = []
    if drawing.outlined_glyphs or outline_text:
        warnings.append('Text is outlined; live text editing is unavailable')
    if drawing.outlined_strokes:
        warnings.append('Outlined strokes cannot be edited as stroke widths or dash patterns')
    if drawing.approximated_strokes:
        warnings.append('Curve subdivision tolerance is not a bound on final outline error')
    if drawing.color_model == 'RGB' and any(i.model == 'CMYK' for i in drawing.images):
        warnings.append('CMYK images in RGB documents may change appearance after Illustrator resaving')
    if drawing.operators.get('ri'):
        warnings.append('Rendering intent is applied to ICC conversion; the original ICC profile is not retained in editable sRGB artwork')
    if drawing.operators.get('i'):
        warnings.append('PDF flatness operators are not preserved in editable artwork')
    return {"input":str(source),"output":str(output),"format":"Illustrator 2020 (24), experimental",
            "warnings":warnings,
            "color_conversions":drawing.color_conversions,
            "transparency_groups":sum(isinstance(i,GroupBoundary) and i.begin for i in drawing.items),
            "layers":[{"name":name,"visible":layer.visible if layer else True,"locked":layer.locked if layer else False,"printable":layer.printable if layer else True} for layer,name,_ in layer_runs(drawing)],
            "conversion_mode":conversion_mode,"rasterized":conversion_mode=='raster-fallback',
            "fallback_reason":fallback_reason,"raster_dpi":raster_dpi if fallback_reason else None,
            "editable_vectors":conversion_mode=='vector',
            "lost_features":['editable paths/text','spot ink separation','layer structure'] if fallback_reason else [],
            "outlined_glyphs":drawing.outlined_glyphs,
            "outlined_strokes":drawing.outlined_strokes,
            "approximated_strokes":drawing.approximated_strokes,
            "stroke_curve_flatness_pt":STROKE_CURVE_FLATNESS if drawing.approximated_strokes else None,
            "text_outlined":(outline_text or drawing.outlined_glyphs>0) and conversion_mode=='vector',"page":index+1,"page_box":list(drawing.box),"painted_paths":len(drawing.paths),
            "subpaths":sum(len(p.paths) for p in drawing.paths),
            "segments":sum(len(s.commands) for p in drawing.paths for s in p.paths),
            "gradients":len({p.state.fill for p in drawing.paths if p.paint != "stroke" and isinstance(p.state.fill,Gradient)}),
            "images":len(drawing.images),"image_soft_masks":sum(i.alpha is not None for i in drawing.images),
            "color_model":drawing.color_model,
            "clipping_paths":sum(len(c.paths) for item in native_items(drawing) for c in item.state.clips),
            "spots":[{"name":s.name,"alternate_space":"Lab" if s.lab is not None else "CMYK","values":list(s.lab if s.lab is not None else s.cmyk)} for s in drawing.spots],
            "pdf_operators":drawing.operators,"private_blocks":private_blocks}
