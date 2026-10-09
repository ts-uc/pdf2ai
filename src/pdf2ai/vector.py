"""Strict PDF path/image reader. Unsupported graphics raise errors instead of disappearing."""
from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field
import math
import re

import pikepdf


class ConversionError(ValueError):
    pass


Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)
BLEND_MODES = {'Normal':0, 'Multiply':1, 'Screen':2, 'Overlay':3,
               'SoftLight':4, 'HardLight':5, 'ColorDodge':6, 'ColorBurn':7,
               'Darken':8, 'Lighten':9, 'Difference':10, 'Exclusion':11, 'Hue':12, 'Saturation':13, 'Color':14, 'Luminosity':15}


def content_instructions(container, resources, ancestors=()):
    """Expand Form invocations with explicit state/resource scope boundaries."""
    for instruction in pikepdf.parse_content_stream(container):
        if not hasattr(instruction, 'operator'):
            raise ConversionError("Inline images are unsupported")
        op,args = str(instruction.operator), list(instruction.operands)
        optional = None
        if op == 'Do':
            obj = resources.get('/XObject', {}).get(str(args[0]))
            optional = obj.get('/OC') if obj is not None else None
            if optional is not None: yield 'BDC',[pikepdf.Name('/OC'),optional],resources
            if obj is not None and str(obj.get('/Subtype')) == '/Form':
                identity = obj.objgen
                if identity in ancestors or len(ancestors)>=32:
                    raise ConversionError("Recursive or excessively nested Form XObject")

                group = obj.get('/Group')
                if group is not None and (str(group.get('/S')) != '/Transparency' or bool(group.get('/I',False)) or bool(group.get('/K',False))):
                    raise ConversionError("Isolated or knockout Form transparency groups are unsupported")
                yield '_form_begin',[obj],resources
                child = obj.get('/Resources', resources)
                yield from content_instructions(obj, child, (*ancestors,identity))
                yield '_form_end',[],resources
                if optional is not None: yield 'EMC',[],resources
                continue
        yield op,args,resources
        if optional is not None: yield 'EMC',[],resources


def compose(left: Matrix, right: Matrix) -> Matrix:
    a, b, c, d, e, f = left
    A, B, C, D, E, F = right
    return (a*A+c*B, b*A+d*B, a*C+c*D, b*C+d*D, a*E+c*F+e, b*E+d*F+f)


def point(matrix: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return (a*x+c*y+e, b*x+d*y+f)


@dataclass(frozen=True)
class Spot:
    name: str
    cmyk: tuple[float, ...]


@dataclass(frozen=True)
class Color:
    model: str = "CMYK"
    values: tuple[float, ...] = (0, 0, 0, 1)
    spot: Spot | None = None


@dataclass(frozen=True)
class Gradient:
    name: str
    stops: tuple[tuple[float, Color], ...]
    start: tuple[float, float]
    end: tuple[float, float]
    radial: bool = False


@dataclass
class State:
    matrix: Matrix = IDENTITY
    fill: Color | Gradient = Color('Gray',(0,))
    stroke: Color | Gradient = Color('Gray',(0,))
    fill_space: object = "/DeviceGray"
    stroke_space: object = "/DeviceGray"
    width: float = 1
    cap: int = 0
    join: int = 0
    miter: float = 10
    dash: tuple[float, ...] = ()
    phase: float = 0
    fill_overprint: bool = False
    stroke_overprint: bool = False
    overprint_mode: int = 0
    fill_alpha: float = 1
    stroke_alpha: float = 1
    blend_mode: str = "Normal"
    clips: tuple = ()
    layer: object = None
    text_font: object = None
    font_size: float = 12
    horizontal_scale: float = 1
    char_spacing: float = 0
    word_spacing: float = 0
    leading: float = 0
    text_rise: float = 0
    text_render_mode: int = 0


@dataclass
class Subpath:
    commands: list[tuple[str, tuple[float, ...]]] = field(default_factory=list)
    closed: bool = False


@dataclass
class PaintedPath:
    paths: list[Subpath]
    state: State
    paint: str
    even_odd: bool
    stroke_scale: float


@dataclass
class Clip:
    paths: list[Subpath]
    even_odd: bool


@dataclass
class Raster:
    width: int
    height: int
    model: str
    pixels: bytes
    alpha: bytes | None
    state: State


@dataclass
class Drawing:
    box: tuple[float, ...]
    paths: list[PaintedPath]
    spots: list[Spot]
    operators: dict[str, int]
    images: list[Raster] = field(default_factory=list)
    items: list = field(default_factory=list)
    color_model: str = "CMYK"
    layers: list = field(default_factory=list)
    outlined_glyphs: int = 0


def read_image(image, state: State) -> Raster:
    if str(image.get("/Subtype")) != "/Image":
        raise ConversionError("Expected an image XObject after Form expansion")
    if image.get("/ImageMask", False):
        raise ConversionError("Image stencil painting is unsupported")
    if image.get("/Matte") is not None:
        raise ConversionError("Custom image Matte is unsupported")
    space = image.get('/ColorSpace')
    indexed = isinstance(space,pikepdf.Array) and str(space[0]) == '/Indexed'
    base = space[1] if indexed else space
    model = {"/DeviceRGB": "RGB", "/DeviceCMYK": "CMYK", "/DeviceGray": "Gray"}.get(str(base))
    bits = int(image.get('/BitsPerComponent',0))
    if model is None or bits not in (1,2,4,8,16) or (indexed and bits==16) or (not indexed and model != 'Gray' and bits not in (8,16)):
        raise ConversionError("Unsupported image color space or bit depth")
    width,height = int(image.Width),int(image.Height)
    if width <= 0 or height <= 0 or width*height > 40_000_000:
        raise ConversionError("Image dimensions exceed the supported limit")
    mask = image.get("/SMask")
    alpha = None
    if mask is not None:
        if not isinstance(mask,pikepdf.Stream) or str(mask.get('/Subtype')) != '/Image':
            raise ConversionError("Only grayscale image soft masks are supported")
        if (int(mask.Width),int(mask.Height)) != (width,height) or str(mask.get('/ColorSpace')) != '/DeviceGray' or int(mask.get('/BitsPerComponent',0)) != 8:
            raise ConversionError("Image soft mask must be 8-bit grayscale with matching dimensions")
        if any(mask.get(k) is not None for k in ('/Decode','/Matte','/Mask','/SMask')):
            raise ConversionError("Custom or nested image soft masks are unsupported")
        alpha = pikepdf.PdfImage(mask).as_pil_image().convert('L').tobytes()
        # PdfImage would combine/premultiply the mask. Extract the unassociated
        # color channels separately and always restore the PDF's original mask.
        del image['/SMask']
    hard_mask = image.get('/Mask')
    decode = image.get('/Decode')
    if decode is not None: del image['/Decode']
    if hard_mask is not None: del image['/Mask']
    try:
        decoded = pikepdf.PdfImage(image).as_pil_image() if bits!=16 else None
        mode = {'RGB':'RGB','CMYK':'CMYK','Gray':'L'}[model]
        if bits==16:
            channels = {'RGB':3,'CMYK':4,'Gray':1}[model]
            raw=image.read_bytes()
            if len(raw)!=width*height*channels*2: raise ConversionError("Invalid 16-bit image sample length")
            pixels=bytes((int.from_bytes(raw[i:i+2],'big')+128)//257 for i in range(0,len(raw),2))
        else:
            if indexed or (model=='Gray' and bits<8): decoded = decoded.convert(mode)
            if decoded.mode != mode: raise ConversionError("Unexpected decoded image color model")
            pixels = decoded.tobytes()
        mask_pixels = pixels
        if decode is not None:
            if indexed: raise ConversionError("Indexed image Decode is unsupported")
            from PIL import Image
            channels = {'RGB':3,'CMYK':4,'Gray':1}[model]
            limits = tuple(map(float,decode))
            if len(limits)!=2*channels or not all(math.isfinite(v) and 0<=v<=1 for v in limits):
                raise ConversionError("Invalid image Decode")
            image_pixels = Image.frombytes(mode,(width,height),pixels)
            tables = [round(255*(limits[2*c]+(limits[2*c+1]-limits[2*c])*i/255)) for c in range(channels) for i in range(256)]
            pixels = image_pixels.point(tables).tobytes()
    finally:
        if mask is not None: image['/SMask'] = mask
        if hard_mask is not None: image['/Mask'] = hard_mask
        if decode is not None: image['/Decode'] = decode
    if hard_mask is not None:
        if alpha is not None: raise ConversionError("Combined hard and soft image masks are unsupported")
        if isinstance(hard_mask,pikepdf.Stream):
            if not hard_mask.get('/ImageMask',False) or int(hard_mask.get('/BitsPerComponent',0))!=1 or (int(hard_mask.Width),int(hard_mask.Height))!=(width,height) or hard_mask.get('/Mask') is not None or hard_mask.get('/SMask') is not None:
                raise ConversionError("Only matching one-bit image masks are supported")
            decode = list(hard_mask.get('/Decode',[0,1]))
            if decode not in ([0,1],[1,0]): raise ConversionError("Unsupported image mask Decode")
            raw = hard_mask.read_bytes();stride = (width+7)//8
            if len(raw)!=stride*height: raise ConversionError("Invalid hard mask data")
            alpha = bytes((255 if ((raw[y*stride+x//8]>>(7-x%8))&1)==int(decode[0]) else 0) for y in range(height) for x in range(width))
        elif isinstance(hard_mask,pikepdf.Array) and not indexed and bits==8:
            channels = {'RGB':3,'CMYK':4,'Gray':1}[model]
            limits = list(map(int,hard_mask))
            if len(limits)!=2*channels or any(not 0<=v<=255 for v in limits) or any(limits[i]>limits[i+1] for i in range(0,len(limits),2)):
                raise ConversionError("Invalid color-key mask")
            alpha = bytes(0 if all(limits[2*c]<=mask_pixels[i+c]<=limits[2*c+1] for c in range(channels)) else 255 for i in range(0,len(pixels),channels))
        else: raise ConversionError("Unsupported hard image mask")
    channels = {'RGB':3,'CMYK':4,'Gray':1}[model]
    if len(pixels) != width*height*channels or (alpha is not None and len(alpha) != width*height):
        raise ConversionError("Decoded image length is invalid")
    return Raster(width,height,model,pixels,alpha,copy(state))


def stencil_paths(image, state):
    """Turn an image stencil into editable, nonoverlapping opaque rectangles."""
    width,height = int(image.Width),int(image.Height)
    if width<=0 or height<=0 or width*height>40_000_000 or int(image.get('/BitsPerComponent',1))!=1:
        raise ConversionError('Invalid image stencil dimensions or bit depth')
    decode=list(image.get('/Decode',[0,1]))
    if decode not in ([0,1],[1,0]):raise ConversionError('Unsupported stencil Decode')
    if image.get('/Mask') is not None or image.get('/SMask') is not None:
        raise ConversionError('Nested stencil masks are unsupported')
    data=image.read_bytes();stride=(width+7)//8
    if len(data)!=stride*height:raise ConversionError('Invalid stencil sample length')
    active={};rectangles=[]
    for y in range(height):
        runs=[];x=0
        while x<width:
            bit=(data[y*stride+x//8]>>(7-x%8))&1
            if bit!=decode[0]:x+=1;continue
            start=x;x+=1
            while x<width and ((data[y*stride+x//8]>>(7-x%8))&1)==decode[0]:x+=1
            runs.append((start,x))
        new={}
        for run in runs:new[run]=active.pop(run,y)
        rectangles.extend((a,b,start,y) for (a,b),start in active.items())
        active=new
        if len(rectangles)+len(active)>100000:raise ConversionError('Stencil exceeds editable rectangle limit')
    rectangles.extend((a,b,start,height) for (a,b),start in active.items())
    result=[]
    for a,b,start,end in rectangles:
        coords=((a/width,1-end/height),(b/width,1-end/height),(b/width,1-start/height),(a/width,1-start/height))
        result.append(Subpath([('m' if i==0 else 'L',point(state.matrix,*v)) for i,v in enumerate(coords)],True))
    return result


def _calculator(function, tint: float) -> tuple[float, ...]:
    """Bounded arithmetic subset of PDF type 4, without executing PostScript."""
    tokens = function.read_bytes().decode("ascii").strip()
    if not (tokens.startswith("{") and tokens.endswith("}")):
        raise ConversionError("Invalid spot tint function")
    tokens = re.sub(r"%[^\r\n]*", "", tokens[1:-1]).split()
    if len(tokens) > 256:
        raise ConversionError("Spot tint function is too complex")
    stack = [tint]
    for token in tokens:
        try:
            number = float(token)
        except ValueError:
            try:
                if token == "dup": stack.append(stack[-1])
                elif token == "exch": stack[-2:] = stack[-2:][::-1]
                elif token == "pop": stack.pop()
                elif token in ("mul", "add", "sub", "div"):
                    right, left = stack.pop(), stack.pop()
                    stack.append({"mul": lambda: left*right, "add": lambda: left+right,
                                  "sub": lambda: left-right, "div": lambda: left/right}[token]())
                else: raise ConversionError(f"Unsupported spot function operator: {token}")
            except (IndexError, ZeroDivisionError) as exc:
                raise ConversionError("Invalid spot function stack") from exc
        else:
            stack.append(number)
        if len(stack) > 32:
            raise ConversionError("Spot function stack limit exceeded")
    if len(stack) != 4 or not all(math.isfinite(v) and -1e-8 <= v <= 1+1e-8 for v in stack):
        raise ConversionError("Spot function must produce four CMYK components")
    return tuple(stack)


def read_spot(space) -> Spot:
    if str(space[0]) != "/Separation" or str(space[2]) != "/DeviceCMYK":
        raise ConversionError("Only Separation spots with DeviceCMYK alternates are supported")
    fn = space[3]
    kind = int(fn.get("/FunctionType", -1))
    if list(fn.get("/Domain", [])) != [0, 1]:
        raise ConversionError("Spot tint function must have domain [0, 1]")
    if kind == 2:
        if float(fn.get("/N", 0)) != 1:
            raise ConversionError("Nonlinear spot tint functions are unsupported")
        zero = tuple(float(v) for v in fn.get("/C0", []))
        full = tuple(float(v) for v in fn.get("/C1", []))
        if zero != (0, 0, 0, 0) or len(full) != 4:
            raise ConversionError("Spot tint must interpolate from CMYK paper white")
    elif kind == 4 and isinstance(fn, pikepdf.Stream):
        full = _calculator(fn, 1)
        # Only multiplicative tint procedures are accepted. Arbitrary approximations
        # would cause the private AI colors to disagree with the PDF representation.
        tokens = fn.read_bytes().decode("ascii")
        number = r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
        expected = (r"\s*\{\s*dup\s+"+number+r"\s+mul\s+exch\s+dup\s+"+number+
                    r"\s+mul\s+exch\s+dup\s+"+number+r"\s+mul\s+exch\s+"+number+r"\s+mul\s*\}\s*")
        if not re.fullmatch(expected, tokens):
            raise ConversionError("Only linear Scribus type-4 spot functions are supported")
    else:
        raise ConversionError(f"Unsupported spot tint function type: {kind}")
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in full):
        raise ConversionError("Invalid CMYK spot values")
    return Spot(str(space[1])[1:], full)


def read_drawing(page, *, root=None) -> Drawing:
    from .layers import read_layers, layer_for
    layer_map = read_layers(root)
    active_layer = None
    marked_layers = []
    rotation = int(page.obj.get('/Rotate',0)) % 360
    unit = float(page.obj.get('/UserUnit',1))
    if rotation not in (0,90,180,270) or not math.isfinite(unit) or unit <= 0:
        raise ConversionError("Invalid page rotation or UserUnit")
    if page.obj.get("/Annots"):
        raise ConversionError("Annotations are unsupported")
    group = page.obj.get('/Group')
    if group is not None:
        if (str(group.get('/S')) != '/Transparency' or bool(group.get('/I',False)) or bool(group.get('/K',False)) or str(group.get('/CS')) not in ('/DeviceRGB','/DeviceCMYK')):
            raise ConversionError("Only nonisolated, nonknockout RGB/CMYK page transparency groups are supported")
    box = tuple(float(v) for v in page.obj.get("/CropBox", page.obj["/MediaBox"]))
    if len(box) != 4 or not all(math.isfinite(v) for v in box) or box[2] <= box[0] or box[3] <= box[1]:
        raise ConversionError("Invalid page box")
    if max(abs(v) for v in box) > 16000:
        raise ConversionError("Page coordinates exceed the supported Illustrator canvas")
    resources = page.obj.get("/Resources", pikepdf.Dictionary())
    spaces = resources.get("/ColorSpace", pikepdf.Dictionary())
    x0,y0,x1,y1 = box
    initial = {0:(1,0,0,1,0,0),90:(0,-1,1,0,-y0,x1),
               180:(-1,0,0,-1,x1,y1),270:(0,1,-1,0,y1,-x0)}[rotation]
    initial = compose((unit,0,0,unit,0,0),initial)
    corners = [point(initial,x,y) for x,y in ((x0,y0),(x1,y1))]
    box = (min(p[0] for p in corners),min(p[1] for p in corners),max(p[0] for p in corners),max(p[1] for p in corners))
    if max(abs(v) for v in box)>16000: raise ConversionError("Scaled page exceeds Illustrator canvas")
    state = State(matrix=initial)
    pattern_base = initial
    scopes = []
    gradient_cache = {}
    stack = []
    paths: list[Subpath] = []
    painted = []
    images = []
    items = []
    pending_clip = None
    used_spots: dict[str, Spot] = {}
    operators: dict[str, int] = {}
    current = start = None

    def color(space, values):
        if str(space) == '/Pattern':
            if len(values) != 1:
                raise ConversionError("Only colored shading patterns are supported")
            pattern = resources.get('/Pattern', {}).get(str(values[0]))
            if pattern is None or int(pattern.get('/PatternType', 0)) != 2 or pattern.get('/ExtGState') is not None:
                raise ConversionError("Only shading patterns without additional graphics state are supported")
            shading = pattern.get('/Shading', {})
            if (int(shading.get('/ShadingType', 0)) not in (2,3) or list(shading.get('/Extend', [])) != [True, True]
                    or list(shading.get('/Domain', [0,1])) != [0,1] or shading.get('/BBox') is not None):
                raise ConversionError("Only extended axial or concentric radial gradients with domain [0,1] are supported")
            space = shading.get('/ColorSpace')
            if str(space) not in ('/DeviceRGB','/DeviceCMYK','/DeviceGray'):
                raise ConversionError("Unsupported gradient color space")
            function = shading.get('/Function', {})
            parts = [function]; bounds = [0.,1.]
            if int(function.get('/FunctionType',0)) == 3:
                parts = list(function.Functions)
                bounds = [0., *map(float,function.Bounds), 1.]
                if list(function.get('/Domain', [])) != [0,1] or list(function.Encode) != [0,1]*len(parts):
                    raise ConversionError("Unsupported gradient stitching function")
            if len(bounds) != len(parts)+1 or len(parts)>256 or any(a>=b for a,b in zip(bounds,bounds[1:])):
                raise ConversionError("Invalid gradient bounds")
            stops = []
            for i,part in enumerate(parts):
                exponent = float(part.get('/N',0))
                if int(part.get('/FunctionType',0)) != 2 or not math.isfinite(exponent) or exponent<=0 or list(part.get('/Domain',[])) != [0,1] or part.get('/Range') is not None:
                    raise ConversionError("Only positive exponential gradient color functions are supported")
                first,last = color(space,part.get('/C0', [])),color(space,part.get('/C1', []))
                if stops and stops[-1][1] != first:
                    raise ConversionError("Discontinuous gradient stops are unsupported")
                if not stops: stops.append((bounds[i],first))
                def subdivide(lo,hi,depth=0):
                    mid=(lo+hi)/2
                    critical=mid
                    slope=(hi**exponent-lo**exponent)/(hi-lo)
                    if exponent!=1 and slope>0:
                        try:
                            candidate=math.exp(math.log(slope/exponent)/(exponent-1))
                            if lo<candidate<hi:critical=candidate
                        except (OverflowError,ValueError):pass
                    linear=lo**exponent+(critical-lo)*slope
                    error=abs(critical**exponent-linear)*max(abs(a-b) for a,b in zip(first.values,last.values))
                    if error>0.25/255:
                        if depth>=20 or len(stops)>256: raise ConversionError("Nonlinear gradient exceeds approximation limit")
                        subdivide(lo,mid,depth+1);subdivide(mid,hi,depth+1)
                    else:
                        fraction=hi**exponent
                        value=last if hi==1 else Color(first.model,tuple(a+(b-a)*fraction for a,b in zip(first.values,last.values)))
                        stops.append((bounds[i]+(bounds[i+1]-bounds[i])*hi,value))
                subdivide(0,1)
            matrix = tuple(map(float,pattern.get('/Matrix', IDENTITY)))
            coords = tuple(map(float,shading.get('/Coords', [])))
            radial = int(shading.ShadingType) == 3
            if radial:
                if len(coords)!=6 or coords[0:2]!=coords[3:5] or coords[2]!=0 or coords[5]<=0:
                    raise ConversionError("Only concentric radial gradients starting at radius zero are supported")
                coords = (coords[0],coords[1],coords[3]+coords[5],coords[4])
            if len(matrix)!=6 or len(coords)!=4 or not all(math.isfinite(v) for v in (*matrix,*coords)):
                raise ConversionError("Invalid gradient coordinates")
            # Pattern matrices map from pattern space to the page's initial user
            # space, independent of the current path CTM.
            matrix = compose(pattern_base,matrix)
            a,b,c,d,_,_ = matrix
            if not math.isclose(a*a+b*b,c*c+d*d,rel_tol=1e-8,abs_tol=1e-8) or not math.isclose(a*c+b*d,0,abs_tol=1e-8):
                raise ConversionError("Nonuniform or skewed gradient matrices are unsupported")
            start,end = point(matrix,*coords[:2]),point(matrix,*coords[2:])
            if math.dist(start,end)<1e-8: raise ConversionError("Degenerate gradient vector")
            key = (tuple(stops),start,end,radial)
            if key not in gradient_cache:
                gradient_cache[key] = Gradient(f"PDF gradient {len(gradient_cache)+1}",tuple(stops),start,end,radial)
            return gradient_cache[key]
        values = tuple(float(v) for v in values)
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
            raise ConversionError("Color components must be in [0, 1]")
        if isinstance(space, pikepdf.Array):
            spot = read_spot(space)
            if len(values) != 1: raise ConversionError("Expected one spot tint")
            if spot.name in used_spots and used_spots[spot.name] != spot:
                raise ConversionError(f"Conflicting spot definitions: {spot.name}")
            used_spots[spot.name] = spot
            return Color("Spot", values, spot)
        model = {"/DeviceCMYK": ("CMYK", 4), "/DeviceRGB": ("RGB", 3), "/DeviceGray": ("Gray", 1)}.get(str(space))
        if not model or len(values) != model[1]:
            raise ConversionError(f"Unsupported color space: {space}")
        return Color(model[0], values)

    text_active = False
    text_matrix = text_line = IDENTITY
    text_clips = []
    font_cache = {}
    outlined_glyphs = 0

    def show_text(string):
        nonlocal text_matrix,outlined_glyphs
        if state.text_font is None: raise ConversionError("Text shown without a font")
        font = state.text_font
        for code in font.codes(string):
            scale = state.font_size/font.units
            glyph_matrix = compose(state.matrix,compose(text_matrix,(scale*state.horizontal_scale,0,0,scale,0,state.text_rise)))
            glyph_paths,width = font.outlines(code,glyph_matrix)
            if any(len(path.commands)>8191 for path in glyph_paths): raise ConversionError("Text glyph exceeds Illustrator segment limit")
            mode = state.text_render_mode
            if mode>=4: text_clips.extend(glyph_paths)
            if glyph_paths and mode not in (3,7):
                paint = 'stroke' if mode in (1,5) else 'both' if mode in (2,6) else 'fill'
                if state.overprint_mode == 0:
                    active_colors = ([state.fill] if paint!='stroke' and state.fill_overprint else []) + ([state.stroke] if paint!='fill' and state.stroke_overprint else [])
                    if any(isinstance(c,Gradient) or c.model in ('CMYK','Gray') for c in active_colors):
                        raise ConversionError('Process-color text overprint mode 0 is unsupported')
                if paint!='fill' and isinstance(state.stroke,Gradient): raise ConversionError("Gradient text strokes are unsupported")
                a,b,c,d,_,_ = state.matrix
                stroke_scale = math.hypot(a,b)
                if paint!='fill' and (state.width==0 or not math.isclose(stroke_scale,math.hypot(c,d),abs_tol=1e-7) or not math.isclose(a*c+b*d,0,abs_tol=1e-7)):
                    raise ConversionError("Hairline/nonuniform text strokes are unsupported")
                paints = ('fill','stroke') if paint=='both' and (isinstance(state.fill,Gradient) or state.fill_alpha!=state.stroke_alpha) else (paint,)
                for paint_mode in paints:
                    glyph_state = copy(state);glyph_state.layer = active_layer
                    item = PaintedPath(glyph_paths,glyph_state,paint_mode,False,stroke_scale)
                    painted.append(item);items.append(item)
            if glyph_paths and mode!=3: outlined_glyphs += 1
            advance = (width*state.font_size/1000+state.char_spacing+(state.word_spacing if code==32 and not font.cid else 0))*state.horizontal_scale
            text_matrix = compose(text_matrix,(1,0,0,1,advance,0))

    marked = 0
    for op,args,resources in content_instructions(page, resources):
        spaces = resources.get('/ColorSpace', {})
        if op == '_form_begin':
            if paths or pending_clip is not None: raise ConversionError("Form within an unfinished path")
            obj = args[0]
            matrix = tuple(map(float,obj.get('/Matrix',IDENTITY)))
            bounds = tuple(map(float,obj.get('/BBox', [])))
            if len(matrix)!=6 or len(bounds)!=4 or not all(math.isfinite(v) for v in (*matrix,*bounds)) or bounds[2]<bounds[0] or bounds[3]<bounds[1]:
                raise ConversionError("Invalid Form matrix or BBox")
            scopes.append((copy(state),pattern_base,len(stack),marked))
            if obj.get('/Group') is not None and (state.fill_alpha!=1 or state.stroke_alpha!=1 or state.blend_mode!='Normal'):
                raise ConversionError("Transparency applied to a whole Form group is unsupported")
            state = copy(state)
            state.matrix = compose(state.matrix,matrix)
            pattern_base = state.matrix
            pts = [point(state.matrix,x,y) for x,y in ((bounds[0],bounds[1]),(bounds[2],bounds[1]),(bounds[2],bounds[3]),(bounds[0],bounds[3]))]
            state.clips += (Clip([Subpath([('m' if i==0 else 'L',p) for i,p in enumerate(pts)],True)],False),)
            continue
        if op == '_form_end':
            previous,base,depth,previous_marked = scopes.pop()
            if paths or pending_clip is not None or len(stack)!=depth or marked!=previous_marked:
                raise ConversionError("Unbalanced Form graphics state")
            state,pattern_base = previous,base
            continue
        operators[op] = operators.get(op, 0) + 1
        if op == 'BT':
            if text_active or paths or pending_clip is not None: raise ConversionError("Invalid text object boundary")
            text_active = True;text_matrix = text_line = IDENTITY;text_clips = []
        elif op == 'ET':
            if not text_active: raise ConversionError("Text object end without begin")
            if text_clips: state.clips += (Clip(text_clips,False),)
            text_active = False;text_clips = []
        elif op in ('Tf','Tc','Tw','Tz','TL','Tr','Ts','Tm','Td','TD','T*','Tj','TJ',"'",'"'):
            if not text_active: raise ConversionError("Text operator outside a text object")
            if op == 'Tf':
                font = resources.get('/Font',{}).get(str(args[0]))
                if font is None: raise ConversionError("Missing PDF font resource")
                from .fonts import OutlineFont
                key = font.objgen
                if key==(0,0): raise ConversionError("Direct PDF font dictionaries are unsupported")
                if key not in font_cache: font_cache[key] = OutlineFont(font)
                state.text_font = font_cache[key];state.font_size = float(args[1])
                if not math.isfinite(state.font_size): raise ConversionError("Invalid text size")
            elif op in ('Tc','Tw','Tz','TL','Tr','Ts'):
                value = float(args[0])
                if not math.isfinite(value): raise ConversionError("Invalid text state")
                if op=='Tr' and value not in range(8): raise ConversionError("Invalid text rendering mode")
                setattr(state,{'Tc':'char_spacing','Tw':'word_spacing','Tz':'horizontal_scale','TL':'leading','Tr':'text_render_mode','Ts':'text_rise'}[op],int(value) if op=='Tr' else value/100 if op=='Tz' else value)
            elif op == 'Tm':
                text_matrix = text_line = tuple(map(float,args))
                if len(text_matrix)!=6 or not all(math.isfinite(v) for v in text_matrix): raise ConversionError("Invalid text matrix")
            elif op in ('Td','TD','T*'):
                dx,dy = (0,-state.leading) if op=='T*' else tuple(map(float,args))
                if not all(math.isfinite(v) for v in (dx,dy)): raise ConversionError("Invalid text position")
                if op=='TD': state.leading = -dy
                text_line = compose(text_line,(1,0,0,1,dx,dy));text_matrix = text_line
            else:
                if op in ("'",'"'):
                    if op=='"':state.word_spacing,state.char_spacing = map(float,args[:2])
                    text_line = compose(text_line,(1,0,0,1,0,-state.leading));text_matrix = text_line
                if op=='TJ':
                    for value in args[0]:
                        if isinstance(value,pikepdf.String):show_text(value)
                        else:
                            shift = -float(value)*state.font_size*state.horizontal_scale/1000
                            if not math.isfinite(shift):raise ConversionError("Invalid text kerning")
                            text_matrix = compose(text_matrix,(1,0,0,1,shift,0))
                else:show_text(args[-1])
        elif op == "q": stack.append(copy(state))
        elif op == "Q":
            if not stack or (scopes and len(stack)<=scopes[-1][2]): raise ConversionError("Unbalanced PDF graphics state")
            state = stack.pop()
        elif op == "cm":
            matrix = tuple(float(v) for v in args)
            if len(matrix) != 6 or not all(math.isfinite(v) for v in matrix): raise ConversionError("Invalid transform")
            state.matrix = compose(state.matrix, matrix)
        elif op in ("cs", "CS"):
            space = spaces.get(str(args[0]), args[0])
            if op == "cs": state.fill_space = space
            else: state.stroke_space = space
        elif op in ("sc", "scn", "SC", "SCN"):
            if op.islower(): state.fill = color(state.fill_space, args)
            else: state.stroke = color(state.stroke_space, args)
        elif op in ("k", "K", "rg", "RG", "g", "G"):
            space = {"k": "/DeviceCMYK", "rg": "/DeviceRGB", "g": "/DeviceGray"}[op.lower()]
            if op.islower(): state.fill_space, state.fill = space, color(space, args)
            else: state.stroke_space, state.stroke = space, color(space, args)
        elif op in ("w", "J", "j", "M"):
            value = float(args[0])
            if not math.isfinite(value): raise ConversionError("Invalid stroke state")
            if op == "w" and value < 0:
                raise ConversionError("Negative stroke widths are unsupported")
            if op in ("J", "j") and value not in (0, 1, 2):
                raise ConversionError("Invalid stroke cap/join")
            if op == "M" and value < 1: raise ConversionError("Invalid miter limit")
            if op == "w": state.width = value
            elif op == "J": state.cap = int(value)
            elif op == "j": state.join = int(value)
            else: state.miter = value
        elif op == "d":
            state.dash = tuple(float(v) for v in args[0]); state.phase = float(args[1])
            if not all(math.isfinite(v) and v >= 0 for v in (*state.dash,state.phase)):
                raise ConversionError("Invalid dash pattern")
            if state.dash and not any(state.dash): raise ConversionError("All-zero dash pattern")
        elif op == "gs":
            settings = resources.get("/ExtGState", {}).get(str(args[0]))
            if settings is None: raise ConversionError("Missing ExtGState")
            for key, value in settings.items():
                if key == "/Type": continue
                if key in ("/ca", "/CA") and 0 <= float(value) <= 1:
                    if key == '/ca': state.fill_alpha = float(value)
                    else: state.stroke_alpha = float(value)
                    continue
                if key == '/BM':
                    modes = list(value) if isinstance(value,pikepdf.Array) else [value]
                    chosen = next((str(v)[1:] for v in modes if str(v)[1:] in BLEND_MODES),None)
                    if chosen is None: raise ConversionError("Unsupported blend mode")
                    state.blend_mode = chosen
                    continue
                if key in ('/LW','/LC','/LJ','/ML','/D'):
                    if key == '/D':
                        state.dash = tuple(map(float,value[0])); state.phase = float(value[1])
                        if not all(math.isfinite(v) and v>=0 for v in (*state.dash,state.phase)) or (state.dash and not any(state.dash)):
                            raise ConversionError("Invalid ExtGState dash pattern")
                    else:
                        v = float(value)
                        if not math.isfinite(v) or (key=='/LW' and v<0) or (key in ('/LC','/LJ') and v not in (0,1,2)) or (key=='/ML' and v<1):
                            raise ConversionError("Invalid ExtGState line style")
                        setattr(state, {'/LW':'width','/LC':'cap','/LJ':'join','/ML':'miter'}[key], int(v) if key in ('/LC','/LJ') else v)
                    continue
                if key in ('/RI','/FL'):
                    continue
                if key == '/AIS' and not bool(value): continue
                if key == "/SMask" and str(value) == "/None": continue
                if key == "/op": state.fill_overprint = bool(value); continue
                if key == "/OP":
                    state.stroke_overprint = bool(value)
                    if "/op" not in settings: state.fill_overprint = bool(value)
                    continue
                if key == "/OPM" and float(value) in (0, 1):
                    state.overprint_mode = int(value)
                    continue
                raise ConversionError(f"Unsupported graphics state setting: {key}")
        elif op == "m":
            current = start = point(state.matrix, *map(float, args))
            paths.append(Subpath([("m", current)]))
        elif op in ("l", "c", "v", "y"):
            if not paths or current is None: raise ConversionError("Path command without moveto")
            if paths[-1].closed:
                raise ConversionError("Continuing a subpath after closepath is unsupported")
            values = [float(v) for v in args]
            transformed = [point(state.matrix, *values[i:i+2]) for i in range(0, len(values), 2)]
            if op == "v": transformed.insert(0, current)
            elif op == "y": transformed.append(transformed[-1])
            coords = tuple(v for pair in transformed for v in pair)
            paths[-1].commands.append(("L" if op == "l" else "C", coords))
            current = transformed[-1]
        elif op == "h":
            if not paths: raise ConversionError("Closepath without path")
            paths[-1].closed = True; current = start
        elif op == "re":
            x,y,w,h = map(float,args)
            pts = [point(state.matrix,X,Y) for X,Y in ((x,y),(x+w,y),(x+w,y+h),(x,y+h))]
            paths.append(Subpath([("m" if i==0 else "L", p) for i,p in enumerate(pts)], True))
            current = start = pts[0]
        elif op in ('W','W*'):
            if not paths or pending_clip is not None: raise ConversionError("Invalid clipping path")
            if any(len(path.commands)>8191 for path in paths): raise ConversionError("Clipping path exceeds the supported segment limit")
            pending_clip = '*' in op
        elif op == 'sh':
            if paths or pending_clip is not None: raise ConversionError("Shading within unfinished path")
            shading = resources.get('/Shading',{}).get(str(args[0]))
            if shading is None: raise ConversionError("Missing shading resource")
            original_resources,original_base = resources,pattern_base
            try:
                resources = pikepdf.Dictionary(Pattern=pikepdf.Dictionary(Direct=pikepdf.Dictionary(PatternType=2,Shading=shading,Matrix=list(state.matrix))))
                pattern_base = IDENTITY
                gradient = color('/Pattern',[pikepdf.Name('/Direct')])
            finally:
                resources,pattern_base = original_resources,original_base
            shading_state = copy(state);shading_state.fill = gradient;shading_state.layer = active_layer
            x0,y0,x1,y1 = box
            # Use the visible clipping bounds instead of a page-sized carrier.
            # Illustrator reconstructs an axial gradient from its carrier path;
            # a huge rectangle behind a small Form clip changes that geometry.
            for clip in state.clips:
                points=[(coords[i],coords[i+1]) for path in clip.paths for _,coords in path.commands for i in range(0,len(coords),2)]
                if points:
                    x0=max(x0,min(p[0] for p in points));y0=max(y0,min(p[1] for p in points))
                    x1=min(x1,max(p[0] for p in points));y1=min(y1,max(p[1] for p in points))
            if x0>=x1 or y0>=y1:continue
            rectangle = Subpath([('m',(x0,y0)),('L',(x1,y0)),('L',(x1,y1)),('L',(x0,y1))],True)
            item = PaintedPath([rectangle],shading_state,'fill',False,1)
            painted.append(item);items.append(item)
        elif op == 'Do':
            if paths or pending_clip is not None: raise ConversionError("Image drawn within an unfinished path")
            image = resources.get('/XObject',{}).get(str(args[0]))
            if image is None: raise ConversionError("Missing image XObject")
            image_state = copy(state);image_state.layer = active_layer
            if image.get('/ImageMask',False):
                if image.get('/Interpolate',False):
                    raise ConversionError('Interpolated image stencils require rasterization')
                if state.fill_overprint and state.overprint_mode==0 and (isinstance(state.fill,Gradient) or state.fill.model in ('CMYK','Gray')):
                    raise ConversionError('Process-color stencil overprint mode 0 is unsupported')
                stencil=stencil_paths(image,image_state)
                if stencil:
                    item=PaintedPath(stencil,image_state,'fill',False,1)
                    painted.append(item);items.append(item)
            else:
                raster = read_image(image,image_state)
                images.append(raster);items.append(raster)
        elif op in ("f", "f*", "F", "S", "s", "B", "B*", "b", "b*", "n"):
            if paths and op != "n":
                if op in ("s", "b", "b*"): paths[-1].closed = True
                paint = "stroke" if op in ("S","s") else "both" if op[0] in "Bb" else "fill"
                if paint != "fill" and state.width == 0:
                    raise ConversionError("Zero-width hairline strokes are unsupported")
                if paint != 'fill' and isinstance(state.stroke, Gradient):
                    raise ConversionError("Gradient strokes are unsupported")
                if state.overprint_mode == 0:
                    active_colors = []
                    if paint != "stroke" and state.fill_overprint: active_colors.append(state.fill)
                    if paint != "fill" and state.stroke_overprint: active_colors.append(state.stroke)
                    if any(isinstance(c, Gradient) or c.model in ("CMYK", "Gray") for c in active_colors):
                        raise ConversionError("Process-color overprint mode 0 is unsupported; mode 1 is required")
                a,b,c,d,_,_ = state.matrix
                scale = math.hypot(a,b)
                if paint != "fill" and (not math.isclose(scale,math.hypot(c,d),abs_tol=1e-7) or not math.isclose(a*c+b*d,0,abs_tol=1e-7)):
                    raise ConversionError("Nonuniform transformed strokes are unsupported")
                if any(len(path.commands)>8191 for path in paths):
                    raise ConversionError("A subpath exceeds Illustrator's 8191-segment limit")
                paints = ('fill','stroke') if paint == 'both' and (isinstance(state.fill,Gradient) or state.fill_alpha != state.stroke_alpha) else (paint,)
                for mode in paints:
                    paint_state = copy(state);paint_state.layer = active_layer
                    item = PaintedPath(paths, paint_state, mode, "*" in op, scale)
                    painted.append(item);items.append(item)
            if pending_clip is not None:
                state.clips += (Clip(paths,pending_clip),)
                pending_clip = None
            paths = [];current = start = None
        elif op in ('BMC','BDC'):
            if paths or pending_clip is not None: raise ConversionError("Layer boundary within unfinished path")
            marked_layers.append(active_layer)
            if str(args[0]) == '/OC':
                if op!='BDC' or len(args)!=2: raise ConversionError("Invalid layer marked content")
                value = args[1]
                if isinstance(value,pikepdf.Name): value = resources.get('/Properties',{}).get(str(value))
                if value is None: raise ConversionError("Missing PDF layer property")
                selected = layer_for(value,layer_map)
                if active_layer is not None and selected != active_layer:
                    raise ConversionError("Nested different PDF layer visibility conditions are unsupported")
                active_layer = selected
            marked += 1
        elif op == 'EMC':
            if marked<=0: raise ConversionError("Unbalanced marked content")
            if paths or pending_clip is not None: raise ConversionError("Layer boundary within unfinished path")
            active_layer = marked_layers.pop()
            marked -= 1
        elif op in ('MP','DP','ri','i'):
            pass  # Structural tags and rendering intent do not change path geometry.
        else:
            raise ConversionError(f"Unsupported PDF operator '{op}'. No output was written. See README for supported paths, images and transparency.")
    if stack or paths or pending_clip is not None or marked or scopes or text_active: raise ConversionError("Unbalanced or unfinished PDF graphics")
    models = set()
    for item in items:
        if isinstance(item,Raster): models.add(item.model)
        else:
            colors = ([item.state.fill] if item.paint=='fill' else [item.state.stroke] if item.paint=='stroke' else [item.state.fill,item.state.stroke])
            for value in colors:
                models.update(c.model for _,c in value.stops) if isinstance(value,Gradient) else models.add(value.model)
    color_model = ('RGB' if str(group.get('/CS')) == '/DeviceRGB' else 'CMYK') if group is not None else ('RGB' if 'RGB' in models and not models.intersection({'CMYK','Spot'}) else 'CMYK')
    return Drawing(box, painted, list(used_spots.values()), operators, images, items, color_model, list(layer_map.values()),outlined_glyphs)
