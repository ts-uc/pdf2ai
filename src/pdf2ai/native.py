"""Generate Illustrator 24 editing streams and PDF containers."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import tempfile
import os
import uuid
from dataclasses import replace

import pikepdf
from PIL import Image

from .codec import MARKER, compress, decode_private
from .vector import Color, ConversionError, Drawing, Gradient, Raster, Clip, Subpath, PaintedPath, BLEND_MODES, read_drawing


def num(value: float) -> str:
    if not math.isfinite(value): raise ConversionError("Nonfinite path coordinate")
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def ps_string(text: str) -> str:
    # UTF-8 octal escapes preserve parentheses, backslashes, controls and names.
    return "(" + "".join(chr(b) if 32 <= b < 127 and b not in (40,41,92)
                         else f"\\{b:03o}" for b in text.encode("utf-8")) + ")"


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
        name = layer.name if layer is not None else 'PDF artwork'
        counts[name] = counts.get(name,0)+1
        if counts[name]>1: name += f' ({counts[name]})'
        result.append((layer,name,items))
    return result


def make_private(drawing: Drawing, title: str) -> tuple[bytes, bytes]:
    runs = layer_runs(drawing)
    x0,y0,x1,y1 = drawing.box
    box = " ".join(num(v) for v in drawing.box)
    header = ["%!PS-Adobe-3.0", "%%Creator: Adobe Illustrator(R) 24.0",
              "%%AI8_CreatorVersion: 24.0.0", f"%%Title: {ps_string(title)}",
              "%%Canvassize: 16383", f"%%BoundingBox: {math.floor(x0)} {math.floor(y0)} {math.ceil(x1)} {math.ceil(y1)}",
              f"%%HiResBoundingBox: {box}", "%%DocumentProcessColors: Cyan Magenta Yellow Black",
              "%AI5_FileFormat 14.0", "%AI12_BuildNumber: 0", "%AI3_ColorUsage: Color",
              "%AI7_ImageSettings: 0", f"%AI3_Cropmarks: {box}", "%AI3_DocumentPreview: None",
              "%AI5_ArtSize: 14400 14400", "%AI5_RulerUnits: 1", "%AI24_LargeCanvasScale: 1",
              f"%AI9_ColorModel: {1 if drawing.color_model == 'RGB' else 2}", "%AI5_ArtFlags: 0 0 0 1 0 0 1 0 0",
              "%AI5_TargetResolution: 800", f"%AI5_NumLayers: {len(runs)}"]
    if drawing.spots:
        header += ["%%DocumentCustomColors: " + ps_string(drawing.spots[0].name)]
        header += ["%%+ " + ps_string(spot.name) for spot in drawing.spots[1:]]
        for i,spot in enumerate(drawing.spots):
            header.append(("%%CMYKCustomColor: " if i == 0 else "%%+ ") +
                          " ".join(num(v) for v in spot.cmyk) + " " + ps_string(spot.name))
    header.append("%%EndComments")
    gradients = list(dict.fromkeys(item.state.fill for item in drawing.paths
                                   if item.paint != 'stroke' and isinstance(item.state.fill, Gradient)))
    body = ["%%BeginProlog", "%%EndProlog", "%%BeginSetup",
            "%AI5_BeginPalette", "0 0 Pb"]
    for spot in drawing.spots:
        body += [color_command(Color('Spot',(1,),spot)),
                 ps_string(spot.name), "Pc"]
    body += ["PB", "%AI5_EndPalette", f"{len(gradients)} Bn"]
    for gradient in gradients:
        body += [f"%AI5_BeginGradient: {ps_string(gradient.name)}",
                 f"{ps_string(gradient.name)} {int(gradient.radial)} {len(gradient.stops)} Bd", "["]
        for position,color in (gradient.stops if gradient.radial else reversed(gradient.stops)):
            command = color_command(color).rsplit(' ',1)[0]
            style = {'Gray':0,'CMYK':1,'RGB':2}[color.model]
            body.append(f"{command} {style} 1 6 50 {num(position*100)} %_BS")
            body.append(f"%_{command} {style} 1 6 50 {num(position*100)} Bs")
        body += ['BD','%AI5_EndGradient']
    body += ["%AI9_BeginDocumentData",
             "%_/Document :", "%_/Dictionary :", "%_16383 /Int (AIDocumentCanvasSize) ,",
             "%_/Array :", "%_/Dictionary :", "%_1 /Bool (IsArtboardDefaultName) ,",
             "%_0 /Bool (IsArtboardSelected) ,", "%_0 /Bool (IsArtboardLocked) ,",
             f"%_{num(x0)} {num(y1)} /RealPointRelToROrigin", "%_ (PositionPoint1) ,",
             f"%_{num(x1)} {num(y0)} /RealPointRelToROrigin", "%_ (PositionPoint2) ,",
             "%_1 /Real (PAR) ,", "%_0 /Int (DisplayMark) ,",
             "%_(Artboard 1) /UnicodeString (Name) ,",
             f"%_{ps_string(str(uuid.uuid4()))} /String (ArtboardUUID) ,",
             "%_; ,", "%_; (ArtboardArray) ,", "%_0 /Int (CropAreaActive) ,",
             "%_;", "%_;", "%AI9_EndDocumentData", "%%EndSetup"]
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
        for path in item.paths:
            body.append(f"{max(0,len(path_commands(path))-1)} As")
            for op,coords in path_commands(path):
                body.append(" ".join(num(v) for v in coords)+" "+op)
            if item.paint != 'stroke' and isinstance(state.fill, Gradient):
                gradient = state.fill
                x,y = gradient.start
                dx,dy = gradient.end[0]-x,gradient.end[1]-y
                body.append('Bb')
                if gradient.radial: body.append('0 0 0 0 Bh')
                # Geometry is already carried by Xm/Bm. Translating Bg again
                # displaces axial gradients when artwork is placed in a Form.
                tx,ty = (0,0)
                if gradient.radial:
                    body.append(f'1 {ps_string(gradient.name)} 0 0 0 1 1 0 0 1 0 0 1 Bg')
                else:
                    angle=math.degrees(math.atan2(dy,dx))
                    body.append(f'1 {ps_string(gradient.name)} 0 0 {num(angle)} 1 1 0 0 1 {num(tx)} {num(ty)} 1 Bg')
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


def convert(source: Path | str, output: Path | str, *, page_number: int | None = None,
            overwrite: bool = False, outline_text: bool = False, ghostscript: str | None = None, raster_fallback: bool = True, raster_dpi: float = 300) -> dict:
    source,output = Path(source),Path(output)
    if source.resolve() == output.resolve(): raise ConversionError("Input and output must differ")
    if output.suffix.lower() != ".ai": raise ConversionError("Output must have an .ai extension")
    if output.exists() and not overwrite: raise ConversionError(f"Output already exists: {output}")
    if not output.parent.is_dir(): raise ConversionError(f"Output directory does not exist: {output.parent}")
    if not math.isfinite(raster_dpi) or not 72<=raster_dpi<=1200:
        raise ConversionError("Raster DPI must be between 72 and 1200")
    with pikepdf.open(source) as pdf:
        if pdf.is_encrypted: raise ConversionError("Encrypted PDFs are unsupported")
        if len(pdf.pages) != 1 and page_number is None:
            raise ConversionError("Multipage PDF: specify --page N; one page per AI file")
        index = (page_number or 1)-1
        if not 0 <= index < len(pdf.pages): raise ConversionError("Page number is out of range")
        page = pdf.pages[index]
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
            drawing = render_drawing(source,index,raster_dpi)
            conversion_mode = 'raster-fallback'
            meta,private = make_private(drawing, source.name)
        # Remove pages in reverse order so page dictionaries/resources remain owned
        # by this PDF, including OutputIntents and embedded color profiles.
        for i in range(len(pdf.pages)-1,-1,-1):
            if i != index: del pdf.pages[i]
        page = pdf.pages[0]
        compressed = MARKER+compress(private)
        chunks = [compressed[i:i+65536] for i in range(0,len(compressed),65536)]
        dictionary = pikepdf.Dictionary(ContainerVersion=12, CreatorVersion=24,
                                        RoundtripVersion=24, RoundtripStreamType=2,
                                        AIMetaData=pdf.make_stream(meta))
        if len(chunks)>1: dictionary.NumBlock = len(chunks)
        for i,chunk in enumerate(chunks,1): dictionary[f"/AIPrivateData{i}"] = pdf.make_stream(chunk)
        timestamp = datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%SZ")
        piece = page.obj.get("/PieceInfo", pikepdf.Dictionary())
        piece.Illustrator = pikepdf.Dictionary(LastModified=pikepdf.String(timestamp),Private=dictionary)
        page.obj.PieceInfo = piece
        pdf.docinfo["/Creator"] = "pdf2ai-vector (experimental Illustrator 2020 writer)"
        # Do not claim PDF/X certification for a newly written file without preflight.
        for key in ("/GTS_PDFXVersion", "/GTS_PDFXConformance"):
            if key in pdf.docinfo: del pdf.docinfo[key]
        with pdf.open_metadata(set_pikepdf_as_editor=False) as metadata:
            metadata["xmp:CreatorTool"] = "pdf2ai-vector"
            for key in ("pdfxid:GTS_PDFXVersion", "pdfx:GTS_PDFXVersion", "pdfx:GTS_PDFXConformance"):
                if key in metadata: del metadata[key]
        fd,temporary = tempfile.mkstemp(prefix=".pdf2ai-",suffix=".ai",dir=output.parent)
        os.close(fd)
        try:
            pdf.save(temporary, min_version="1.6", compress_streams=True)
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
    return {"input":str(source),"output":str(output),"format":"Illustrator 2020 (24), experimental",
            "layers":[{"name":name,"visible":layer.visible if layer else True,"locked":layer.locked if layer else False,"printable":layer.printable if layer else True} for layer,name,_ in layer_runs(drawing)],
            "conversion_mode":conversion_mode,"rasterized":conversion_mode=='raster-fallback',
            "fallback_reason":fallback_reason,"raster_dpi":raster_dpi if fallback_reason else None,
            "editable_vectors":conversion_mode=='vector',
            "lost_features":['editable paths/text','spot ink separation','layer structure'] if fallback_reason else [],
            "outlined_glyphs":drawing.outlined_glyphs,
            "text_outlined":(outline_text or drawing.outlined_glyphs>0) and conversion_mode=='vector',"page":index+1,"page_box":list(drawing.box),"painted_paths":len(drawing.paths),
            "subpaths":sum(len(p.paths) for p in drawing.paths),
            "segments":sum(len(s.commands) for p in drawing.paths for s in p.paths),
            "gradients":len({p.state.fill for p in drawing.paths if p.paint != "stroke" and isinstance(p.state.fill,Gradient)}),
            "images":len(drawing.images),"image_soft_masks":sum(i.alpha is not None for i in drawing.images),
            "color_model":drawing.color_model,
            "clipping_paths":sum(len(c.paths) for item in native_items(drawing) for c in item.state.clips),
            "spots":[{"name":s.name,"alternate_space":"Lab" if s.lab is not None else "CMYK","values":list(s.lab if s.lab is not None else s.cmyk)} for s in drawing.spots],
            "pdf_operators":drawing.operators,"private_blocks":len(chunks)}
