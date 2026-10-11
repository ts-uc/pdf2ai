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
RENDERING_INTENTS = {'/Perceptual':0,'/RelativeColorimetric':1,'/Saturation':2,'/AbsoluteColorimetric':3}


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
                if group is not None and str(group.get('/S')) != '/Transparency':
                    raise ConversionError("Unsupported Form group type")
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
    lab: tuple[float, ...] | None = None


@dataclass(frozen=True)
class Color:
    model: str = "CMYK"
    values: tuple[float, ...] = (0, 0, 0, 1)
    spot: Spot | None = None
    icc_profile: bytes | None = None
    icc_model: str | None = None
    icc_values: tuple[float,...] | None = None


@dataclass(frozen=True)
class Gradient:
    name: str
    stops: tuple[tuple[float, Color], ...]
    start: tuple[float, float]
    end: tuple[float, float]
    radial: bool = False
    focus: tuple[float, float] | None = None


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
    rendering_intent: int = 1


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
    color_conversion: str | None = None


@dataclass
class GroupBoundary:
    state: State
    begin: bool
    isolated: bool = False
    color_model: str | None = None
    knockout: bool = False


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
    outlined_strokes: int = 0
    approximated_strokes: int = 0
    color_conversions: list = field(default_factory=list)


STROKE_CURVE_FLATNESS = 0.0025


def flatten_stroke_path(path,state):
    """Adaptively subdivide cubic centerlines before constructing stroke bands."""
    a,b,c,d,_,_=state.matrix;det=a*d-b*c
    if abs(det)<1e-12:raise ConversionError('Singular stroke transformation')
    radius_bound=state.width/2*math.sqrt(a*a+b*b+c*c+d*d)
    commands=[]
    def midpoint(p,q):return (p[0]+q[0])/2,(p[1]+q[1])/2
    def flatten(p0,p1,p2,p3,depth=0):
        dx,dy=p3[0]-p0[0],p3[1]-p0[1];length=math.hypot(dx,dy)
        flat=length>1e-12 and max(abs(dx*(p[1]-p0[1])-dy*(p[0]-p0[0]))/length for p in (p1,p2))<=STROKE_CURVE_FLATNESS
        ux,uy=(d*dx-c*dy)/det,(-b*dx+a*dy)/det;user_length=math.hypot(ux,uy)
        if flat and user_length>1e-12:
            for first,last in zip((p0,p1,p2),(p1,p2,p3)):
                X,Y=last[0]-first[0],last[1]-first[1]
                vx,vy=(d*X-c*Y)/det,(-b*X+a*Y)/det;size=math.hypot(vx,vy)
                if size>1e-12:
                    cosine=max(-1,min(1,(vx*ux+vy*uy)/(size*user_length)))
                    if cosine<=0 or radius_bound*(1-cosine)>STROKE_CURVE_FLATNESS:flat=False;break
        if flat:
            if not commands or commands[-1][1]!=p3:commands.append(('L',p3))
            if len(commands)>8191:raise ConversionError('Stroke curve exceeds subdivision limit')
            return
        if depth>=22:raise ConversionError('Stroke curve cannot meet subdivision criteria')
        a0,a1,a2=midpoint(p0,p1),midpoint(p1,p2),midpoint(p2,p3)
        b0,b1=midpoint(a0,a1),midpoint(a1,a2);middle=midpoint(b0,b1)
        flatten(p0,a0,b0,middle,depth+1);flatten(middle,b1,a2,p3,depth+1)
    current=None
    for op,coords in path.commands:
        if op=='m':commands.append((op,coords));current=coords
        elif op=='L':commands.append((op,coords));current=coords
        elif op=='C' and current is not None:
            p1,p2,p3=coords[:2],coords[2:4],coords[4:6]
            if current==p1==p2==p3:continue
            flatten(current,p1,p2,p3);current=p3
        else:raise ConversionError('Unsupported stroke curve command')
    return Subpath(commands,path.closed)


def outline_rectangle_stroke(path,state):
    """A mitered rectangular ring, constructed in the stroking user space."""
    if state.dash or state.join!=0 or state.miter<math.sqrt(2):
        raise ConversionError('Nonuniform rectangle strokes require solid miter joins with sufficient miter limit')
    if len(path.commands)!=4 or [op for op,_ in path.commands]!=['m','L','L','L']:
        raise ConversionError('Unsupported nonuniform closed stroke')
    a,b,c,d,_,_=state.matrix;det=a*d-b*c
    if abs(det)<1e-12:raise ConversionError('Singular stroke transformation')
    pts=[v for _,v in path.commands];origin=pts[0]
    def inverse_delta(p):
        x,y=p[0]-origin[0],p[1]-origin[1]
        return (d*x-c*y)/det,(-b*x+a*y)/det
    u,v=inverse_delta(pts[1]),inverse_delta(pts[3])
    w,h=math.hypot(*u),math.hypot(*v)
    if min(w,h)<1e-12:raise ConversionError('Degenerate nonuniform rectangle')
    if abs(u[0]*v[0]+u[1]*v[1])>1e-8*w*h or not all(math.isclose(x,y,rel_tol=1e-8,abs_tol=1e-8) for x,y in zip(inverse_delta(pts[2]),(u[0]+v[0],u[1]+v[1]))):
        raise ConversionError('Nonuniform closed stroke is not a rectangle in stroking user space')
    def transform(x,y):
        X,Y=x*u[0]/w+y*v[0]/h,x*u[1]/w+y*v[1]/h
        return origin[0]+a*X+c*Y,origin[1]+b*X+d*Y
    r=state.width/2
    outer=[(-r,-r),(w+r,-r),(w+r,h+r),(-r,h+r)]
    inner=[(r,r),(w-r,r),(w-r,h-r),(r,h-r)]
    # All expanded strokes have clockwise outer boundaries in user space,
    # so overlapping subpaths do not cancel under the nonzero filling rule.
    if u[0]*v[1]-u[1]*v[0]>0:outer.reverse()
    else:inner.reverse()
    result=[]
    for contour in [outer]+([inner] if w>2*r and h>2*r else []):
        result.append(Subpath([('m' if i==0 else 'L',transform(*p)) for i,p in enumerate(contour)],True))
    return result


def stroke_circle(center,r,matrix):
    k=4*(math.sqrt(2)-1)/3
    arcs=(((k*r,r),(r,k*r),(r,0)),((r,-k*r),(k*r,-r),(0,-r)),
          ((-k*r,-r),(-r,-k*r),(-r,0)),((-r,k*r),(-k*r,r),(0,r)))
    commands=[('m',point(matrix,center[0],center[1]+r))]
    for arc in arcs:
        commands.append(('C',tuple(v for x,y in arc for v in point(matrix,center[0]+x,center[1]+y))))
    return Subpath(commands,True)


def outline_dashed_polyline(pts,closed,state):
    """Cut dashes by total user-space arc length, retaining joins inside each dash."""
    from bisect import bisect_left, bisect_right
    vertices=pts+([pts[0]] if closed else [])
    lengths=[0.0]
    for first,last in zip(vertices,vertices[1:]):
        lengths.append(lengths[-1]+math.dist(first,last))
    total=lengths[-1]
    if total<1e-12:raise ConversionError('Degenerate nonuniform dashed polyline')
    pattern=state.dash*2 if len(state.dash)%2 else state.dash
    phase=state.phase%sum(pattern);index=0
    while phase>0 and phase>=pattern[index]:
        phase-=pattern[index];index=(index+1)%len(pattern)
    remaining=pattern[index]-phase;position=0;intervals=[];steps=0
    while position<total or (position==total and remaining==0):
        end=min(total,position+remaining)
        if remaining>0 and end<=position:raise ConversionError('Dash interval is below coordinate precision')
        if index%2==0:intervals.append((position,end))
        if end<position+remaining:break
        position=end;index=(index+1)%len(pattern);remaining=pattern[index];steps+=1
        if steps>20000:raise ConversionError('Outlined dash pattern exceeds complexity limit')
    def location(distance):
        if distance>=total:return vertices[-1]
        i=min(bisect_right(lengths,distance)-1,len(vertices)-2)
        fraction=(distance-lengths[i])/(lengths[i+1]-lengths[i])
        first,last=vertices[i:i+2]
        return first[0]+fraction*(last[0]-first[0]),first[1]+fraction*(last[1]-first[1])
    fragments=[];dots=[]
    for first,last in intervals:
        if first==last:
            dots.append(location(first));continue
        interior=vertices[bisect_right(lengths,first):bisect_left(lengths,last)]
        fragments.append([location(first),*interior,location(last)])
    # A dash that spans the closepath seam is one stroke with a join there.
    whole=closed and len(intervals)==1 and intervals[0]==(0,total)
    if closed and len(fragments)>1 and intervals[0][0]==0 and intervals[-1][1]==total and intervals[0][1]>0 and intervals[-1][0]<total:
        fragments=[fragments[-1]+fragments[0][1:],*fragments[1:-1]]
    solid=copy(state);solid.dash=();solid.phase=0;result=[]
    for fragment in fragments:
        path=Subpath([('m' if i==0 else 'L',point(state.matrix,*v)) for i,v in enumerate(fragment)],whole)
        result.extend(outline_polyline_stroke(path,solid))
        if len(result)>60000:raise ConversionError('Outlined dash pattern exceeds complexity limit')
    result.extend(stroke_circle(center,state.width/2,state.matrix) for center in dots)
    if len(result)>60000:raise ConversionError('Outlined dash pattern exceeds complexity limit')
    return result


def outline_polyline_stroke(path,state):
    """Union of stroke bands, endpoint caps, and the PDF join regions."""
    if not path.commands or path.commands[0][0]!='m' or any(op!='L' for op,_ in path.commands[1:]):
        raise ConversionError('Nonuniform curved strokes are unsupported')
    a,b,c,d,e,f=state.matrix;det=a*d-b*c
    if abs(det)<1e-12:raise ConversionError('Singular stroke transformation')
    pts=[((d*(x-e)-c*(y-f))/det,(-b*(x-e)+a*(y-f))/det) for _,(x,y) in path.commands]
    pts=[v for i,v in enumerate(pts) if i==0 or v!=pts[i-1]]
    if path.closed and len(pts)>1 and pts[-1]==pts[0]:pts.pop()
    if len(pts)<2:raise ConversionError('Degenerate nonuniform polyline')
    if state.dash:return outline_dashed_polyline(pts,path.closed,state)
    segments=list(zip(pts,pts[1:]+([pts[0]] if path.closed else [])))
    directions=[];result=[];r=state.width/2
    def polygon(vertices):
        area=sum(x*Y-y*X for (x,y),(X,Y) in zip(vertices,vertices[1:]+vertices[:1]))
        if area>0:vertices=list(reversed(vertices))
        result.append(Subpath([('m' if i==0 else 'L',point(state.matrix,*v)) for i,v in enumerate(vertices)],True))
    for first,last in segments:
        dx,dy=last[0]-first[0],last[1]-first[1];length=math.hypot(dx,dy)
        if length<1e-12:raise ConversionError('Degenerate nonuniform polyline segment')
        t=(dx/length,dy/length);directions.append(t);nx,ny=-t[1]*r,t[0]*r
        polygon([(first[0]+nx,first[1]+ny),(last[0]+nx,last[1]+ny),(last[0]-nx,last[1]-ny),(first[0]-nx,first[1]-ny)])
    for i in (range(len(pts)) if path.closed else range(1,len(pts)-1)):
        vertex=pts[i];before=directions[(i-1)%len(directions)];after=directions[i%len(directions)]
        cross=before[0]*after[1]-before[1]*after[0];dot=before[0]*after[0]+before[1]*after[1]
        if abs(cross)<1e-10:
            if dot<0:raise ConversionError('Reversing nonuniform polyline joins are unsupported')
            continue
        if state.join==1:
            result.append(stroke_circle(vertex,r,state.matrix));continue
        sign=-1 if cross>0 else 1
        n1=(-before[1]*r*sign,before[0]*r*sign);n2=(-after[1]*r*sign,after[0]*r*sign)
        first=(vertex[0]+n1[0],vertex[1]+n1[1]);last=(vertex[0]+n2[0],vertex[1]+n2[1])
        scale=((last[0]-first[0])*after[1]-(last[1]-first[1])*after[0])/cross
        miter=(first[0]+scale*before[0],first[1]+scale*before[1])
        if state.join==0 and math.dist(vertex,miter)<=state.miter*r:
            polygon([vertex,first,miter,last])
        else:polygon([vertex,first,last])
    if not path.closed:
        for center,t in ((pts[0],directions[0]),(pts[-1],directions[-1])):
            if state.cap==1:result.append(stroke_circle(center,r,state.matrix))
            elif state.cap==2:
                nx,ny=-t[1]*r,t[0]*r;dx,dy=t[0]*r,t[1]*r
                polygon([(center[0]+dx+nx,center[1]+dy+ny),(center[0]-dx+nx,center[1]-dy+ny),(center[0]-dx-nx,center[1]-dy-ny),(center[0]+dx-nx,center[1]+dy-ny)])
    if len(result)>60000:raise ConversionError('Outlined polyline exceeds complexity limit')
    return result


def outline_straight_strokes(paths, state):
    """Expand single-segment strokes in stroking user space, then apply CTM."""
    if any(v==0 for v in state.dash) and state.cap!=1:
        raise ConversionError('Zero-length nonuniform dashes require round caps')
    a,b,c,d,_,_ = state.matrix
    det = a*d-b*c
    if abs(det)<1e-12:
        raise ConversionError('Singular stroke transformation')
    result=[]
    for path in paths:
        if any(op=='C' for op,_ in path.commands):path=flatten_stroke_path(path,state)
        if path.closed or len(path.commands)!=2:
            if path.closed and len(path.commands)==4 and not state.dash and state.join==0 and state.miter>=math.sqrt(2):
                try:
                    result.extend(outline_rectangle_stroke(path,state));continue
                except ConversionError:
                    pass  # Other polygons use the general join construction.
            result.extend(outline_polyline_stroke(path,state));continue
        if [op for op,_ in path.commands]!=['m','L']:
            raise ConversionError('Nonuniform curved strokes are unsupported')
        start,end = (coords for _,coords in path.commands)
        dx,dy=end[0]-start[0],end[1]-start[1]
        ux,uy=(d*dx-c*dy)/det,(-b*dx+a*dy)/det
        length=math.hypot(ux,uy)
        if length<1e-12:
            raise ConversionError('Degenerate nonuniform stroke')
        if state.dash:
            pattern=state.dash*2 if len(state.dash)%2 else state.dash
            phase=state.phase%sum(pattern)
            index=0
            while phase>0 and phase>=pattern[index]:
                phase-=pattern[index];index=(index+1)%len(pattern)
            remaining=pattern[index]-phase
            position=0
            solid=copy(state);solid.dash=();solid.phase=0
            steps=0
            while position<length or (position==length and remaining==0):
                end_position=min(length,position+remaining)
                if remaining>0 and end_position<=position:
                    raise ConversionError('Dash interval is below coordinate precision')
                if index%2==0:
                    first=(start[0]+dx*position/length,start[1]+dy*position/length)
                    last=(start[0]+dx*end_position/length,start[1]+dy*end_position/length)
                    if remaining==0:
                        x,y=first;center=((d*(x-state.matrix[4])-c*(y-state.matrix[5]))/det,(-b*(x-state.matrix[4])+a*(y-state.matrix[5]))/det)
                        result.append(stroke_circle(center,state.width/2,state.matrix))
                    else:
                        result.extend(outline_straight_strokes([Subpath([('m',first),('L',last)])],solid))
                if end_position<position+remaining:break
                position=end_position;index=(index+1)%len(pattern);remaining=pattern[index]
                steps+=1
                if steps>20000 or len(result)>60000:
                    raise ConversionError('Outlined dash pattern exceeds complexity limit')
            continue
        tx,ty=ux/length,uy/length
        def transform(x,y):
            X,Y=x*tx-y*ty,x*ty+y*tx
            return start[0]+a*X+c*Y,start[1]+b*X+d*Y
        radius=state.width/2
        extra=radius if state.cap==2 else 0
        corners=((-extra,radius),(length+extra,radius),(length+extra,-radius),(-extra,-radius))
        result.append(Subpath([('m' if i==0 else 'L',transform(*v)) for i,v in enumerate(corners)],True))
        if state.cap==1:
            # Four cubic arcs approximate a circle; affine CTM gives elliptical caps.
            k=4*(math.sqrt(2)-1)/3; r=radius
            for center in (0,length):
                arcs=(((k*r,r),(r,k*r),(r,0)),((r,-k*r),(k*r,-r),(0,-r)),
                      ((-k*r,-r),(-r,-k*r),(-r,0)),((-r,k*r),(-k*r,r),(0,r)))
                commands=[('m',transform(center,r))]
                for arc in arcs:
                    commands.append(('C',tuple(v for x,y in arc for v in transform(center+x,y))))
                result.append(Subpath(commands,True))
    return result


def read_image(image, state: State, *, color_space=None) -> Raster:
    if str(image.get("/Subtype")) != "/Image":
        raise ConversionError("Expected an image XObject after Form expansion")
    if image.get("/ImageMask", False):
        raise ConversionError("Image stencil painting is unsupported")
    if image.get("/Matte") is not None:
        raise ConversionError("Custom image Matte is unsupported")
    space = color_space if color_space is not None else image.get('/ColorSpace')
    indexed = isinstance(space,pikepdf.Array) and str(space[0]) == '/Indexed'
    base = space[1] if indexed else space
    profile = None
    if isinstance(base,pikepdf.Array) and str(base[0]) == '/ICCBased':
        profile = base[1]
        if not isinstance(profile,pikepdf.Stream):raise ConversionError('Invalid ICC profile stream')
        model_name = {1:'/DeviceGray',3:'/DeviceRGB',4:'/DeviceCMYK'}.get(int(profile.get('/N',0)))
        if model_name is None:raise ConversionError('Unsupported ICC channel count')
        if list(profile.get('/Range',[0,1]*int(profile.N))) != [0,1]*int(profile.N):
            raise ConversionError('Nonstandard ICC component Range is unsupported')
        base = pikepdf.Name(model_name)
    model = {"/DeviceRGB": "RGB", "/DeviceCMYK": "CMYK", "/DeviceGray": "Gray"}.get(str(base))
    bits = int(image.get('/BitsPerComponent',0))
    if model is None or bits not in (1,2,4,8,16) or (indexed and bits==16) or (not indexed and model != 'Gray' and bits not in (8,16)):
        raise ConversionError("Unsupported image color space or bit depth")
    width,height = int(image.Width),int(image.Height)
    if width <= 0 or height <= 0 or width*height > 40_000_000:
        raise ConversionError("Image dimensions exceed the supported limit")
    mask = image.get("/SMask")
    alpha = None
    matte = None
    if mask is not None:
        if not isinstance(mask,pikepdf.Stream) or str(mask.get('/Subtype')) != '/Image':
            raise ConversionError("Only grayscale image soft masks are supported")
        mask_bits = int(mask.get('/BitsPerComponent',0))
        if (int(mask.Width),int(mask.Height)) != (width,height) or str(mask.get('/ColorSpace')) != '/DeviceGray' or mask_bits not in (1,2,4,8,16):
            raise ConversionError("Image soft mask must be grayscale with matching dimensions")
        if any(mask.get(k) is not None for k in ('/Mask','/SMask')):
            raise ConversionError("Nested image soft masks are unsupported")
        if mask.get('/Matte') is not None:
            try:
                matte = tuple(map(float,mask.Matte))
            except (ValueError,TypeError) as exc:
                raise ConversionError('Invalid soft mask Matte') from exc
            channels = {'RGB':3,'CMYK':4,'Gray':1}[model]
            if indexed or len(matte)!=channels or not all(math.isfinite(v) and 0<=v<=1 for v in matte):
                raise ConversionError('Invalid or unsupported soft mask Matte')
        mask_decode = mask.get('/Decode')
        if mask_decode is not None:
            limits = tuple(map(float,mask_decode))
            if len(limits)!=2 or not all(math.isfinite(v) and 0<=v<=1 for v in limits):
                raise ConversionError('Invalid soft mask Decode')
            del mask['/Decode']
        try:
            if mask_bits == 16:
                raw = mask.read_bytes()
                if len(raw)!=width*height*2:
                    raise ConversionError('Invalid 16-bit soft mask sample length')
                alpha = bytes((int.from_bytes(raw[i:i+2],'big')+128)//257 for i in range(0,len(raw),2))
            else:
                alpha = pikepdf.PdfImage(mask).as_pil_image().convert('L').tobytes()
        finally:
            if mask_decode is not None: mask['/Decode'] = mask_decode
        if mask_decode is not None:
            table = bytes(round(255*(limits[0]+(limits[1]-limits[0])*i/255)) for i in range(256))
            alpha = alpha.translate(table)
        # PdfImage would combine/premultiply the mask. Extract the unassociated
        # color channels separately and always restore the PDF's original mask.
        del image['/SMask']
    hard_mask = image.get('/Mask')
    decode = image.get('/Decode')
    if decode is not None: del image['/Decode']
    if hard_mask is not None: del image['/Mask']
    original_space = image.get('/ColorSpace')
    if profile is not None:
        image['/ColorSpace'] = pikepdf.Array([space[0],base,space[2],space[3]]) if indexed else base
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
        if profile is not None: image['/ColorSpace'] = original_space
        if mask is not None: image['/SMask'] = mask
        if hard_mask is not None: image['/Mask'] = hard_mask
        if decode is not None: image['/Decode'] = decode
    if hard_mask is not None:
        if alpha is not None: raise ConversionError("Combined hard and soft image masks are unsupported")
        if isinstance(hard_mask,pikepdf.Array):
            try:
                values=tuple(map(float,hard_mask))
            except (ValueError,TypeError,OverflowError) as exc:
                raise ConversionError('Invalid color-key mask samples') from exc
            if any(not math.isfinite(v) or v!=math.floor(v) for v in values):
                raise ConversionError('Color-key mask samples must be integers')
        if isinstance(hard_mask,pikepdf.Stream):
            if not hard_mask.get('/ImageMask',False) or int(hard_mask.get('/BitsPerComponent',0))!=1 or (int(hard_mask.Width),int(hard_mask.Height))!=(width,height) or hard_mask.get('/Mask') is not None or hard_mask.get('/SMask') is not None:
                raise ConversionError("Only matching one-bit image masks are supported")
            decode = list(hard_mask.get('/Decode',[0,1]))
            if decode not in ([0,1],[1,0]): raise ConversionError("Unsupported image mask Decode")
            raw = hard_mask.read_bytes();stride = (width+7)//8
            if len(raw)!=stride*height: raise ConversionError("Invalid hard mask data")
            alpha = bytes((255 if ((raw[y*stride+x//8]>>(7-x%8))&1)==int(decode[0]) else 0) for y in range(height) for x in range(width))
        elif isinstance(hard_mask,pikepdf.Array) and indexed:
            limits=list(map(int,hard_mask));maximum=(1<<bits)-1
            if len(limits)!=2 or not 0<=limits[0]<=limits[1]<=maximum:
                raise ConversionError('Invalid Indexed color-key mask')
            raw=image.read_bytes();stride=(width*bits+7)//8
            if len(raw)!=stride*height:raise ConversionError('Invalid Indexed image sample length')
            alpha=bytes(0 if limits[0]<=((raw[y*stride+x*bits//8]>>(8-bits-x*bits%8))&maximum)<=limits[1] else 255
                        for y in range(height) for x in range(width))
        elif isinstance(hard_mask,pikepdf.Array) and bits==8:
            channels = {'RGB':3,'CMYK':4,'Gray':1}[model]
            limits = list(map(int,hard_mask))
            if len(limits)!=2*channels or any(not 0<=v<=255 for v in limits) or any(limits[i]>limits[i+1] for i in range(0,len(limits),2)):
                raise ConversionError("Invalid color-key mask")
            alpha = bytes(0 if all(limits[2*c]<=mask_pixels[i+c]<=limits[2*c+1] for c in range(channels)) else 255 for i in range(0,len(pixels),channels))
        else: raise ConversionError("Unsupported hard image mask")
    channels = {'RGB':3,'CMYK':4,'Gray':1}[model]
    if len(pixels) != width*height*channels or (alpha is not None and len(alpha) != width*height):
        raise ConversionError("Decoded image length is invalid")
    if matte is not None:
        # PDF 32000-1, 11.6.5.3: c' = alpha*c + (1-alpha)*matte.
        # Recover straight color after Decode, before storing the separate alpha.
        # Color under zero alpha is undefined; choose zero deterministically.
        tables = {(a,c): bytes(max(0,min(255,round((v-255*matte[c])*255/a+255*matte[c])))
                              for v in range(256)) if a else bytes(256)
                  for a in set(alpha) for c in range(channels)}
        pixels = bytes(tables[(alpha[i//channels],i%channels)][v] for i,v in enumerate(pixels))
    if profile is not None:
        from .color_management import icc_to_rgb
        pixels = icc_to_rgb(pixels,width,height,model,profile.read_bytes(),state.rendering_intent)
        model = 'RGB'
    return Raster(width,height,model,pixels,alpha,copy(state),'ICC image converted to sRGB using LittleCMS' if profile is not None else None)


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
    from .dic import dic_color, dic_name
    name = str(space[1])[1:]
    reference = dic_color(name)
    if reference is not None:
        name = dic_name(name)
    alternate = space[2]
    if isinstance(alternate,pikepdf.Array) and str(alternate[0]) == '/ICCBased':
        profile = alternate[1]
        if int(profile.get('/N',0)) == 3 and profile.read_bytes()[16:20] == b'Lab ':
            alternate = profile.get('/Alternate')
    is_lab = isinstance(alternate,pikepdf.Array) and str(alternate[0]) == '/Lab'
    if str(space[0]) != "/Separation" or not (str(alternate) == '/DeviceCMYK' or is_lab and reference):
        raise ConversionError("Only CMYK or registered DIC Lab Separation spots are supported")
    if is_lab:
        white = tuple(float(v) for v in alternate[1].get('/WhitePoint',[]))
        if len(white)!=3 or any(abs(a-b)>0.001 for a,b in zip(white,(0.964203,1,0.824905))):
            raise ConversionError("DIC Lab spots require D50 white point")
    fn = space[3]
    kind = int(fn.get("/FunctionType", -1))
    if list(fn.get("/Domain", [])) != [0, 1]:
        raise ConversionError("Spot tint function must have domain [0, 1]")
    if kind == 2:
        if float(fn.get("/N", 0)) != 1:
            raise ConversionError("Nonlinear spot tint functions are unsupported")
        zero = tuple(float(v) for v in fn.get("/C0", []))
        full = tuple(float(v) for v in fn.get("/C1", []))
        if zero != ((100,0,0) if is_lab else (0,0,0,0)) or len(full) != (3 if is_lab else 4):
            raise ConversionError("Spot tint must interpolate from paper white")
    elif kind == 4 and not is_lab and isinstance(fn, pikepdf.Stream):
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
    bounds = ((0,100),(-128,127),(-128,127)) if is_lab else ((0,1),)*4
    if not all(math.isfinite(v) and lo <= v <= hi for v,(lo,hi) in zip(full,bounds)):
        raise ConversionError("Invalid spot values")
    return Spot(name, tuple(reference['cmyk']), full if is_lab else tuple(reference['lab'])) if reference else Spot(name, full)


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
    conversions = []

    def color(space, values):
        default = {'/DeviceRGB':'/DefaultRGB','/DeviceCMYK':'/DefaultCMYK','/DeviceGray':'/DefaultGray'}.get(str(space))
        if default and default in resources.get('/ColorSpace',{}):
            replacement = resources.ColorSpace[default]
            if not isinstance(replacement,pikepdf.Array) or str(replacement[0]) != '/ICCBased':
                raise ConversionError('Unsupported default device color space replacement')
            space = replacement
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
            focus = None
            if radial:
                if len(coords)!=6 or not all(math.isfinite(v) for v in coords) or coords[2]!=0 or coords[5]<=0 or math.dist(coords[:2],coords[3:5])>=coords[5]:
                    raise ConversionError("Only concentric or interior-focus radial gradients starting at radius zero are supported")
                focus = coords[:2] if coords[:2]!=coords[3:5] else None
                coords = (coords[3],coords[4],coords[3]+coords[5],coords[4])
            if len(matrix)!=6 or len(coords)!=4 or not all(math.isfinite(v) for v in (*matrix,*coords)):
                raise ConversionError("Invalid gradient coordinates")
            # Pattern matrices map from pattern space to the page's initial user
            # space, independent of the current path CTM.
            matrix = compose(pattern_base,matrix)
            a,b,c,d,_,_ = matrix
            if radial and (not math.isclose(a*a+b*b,c*c+d*d,rel_tol=1e-8,abs_tol=1e-8) or not math.isclose(a*c+b*d,0,abs_tol=1e-8)):
                raise ConversionError("Nonuniform or skewed gradient matrices are unsupported")
            start,end = point(matrix,*coords[:2]),point(matrix,*coords[2:])
            if focus is not None: focus = point(matrix,*focus)
            if not radial:
                # Axial color varies along a covector. Transforming endpoints
                # alone is incorrect for shear/nonuniform scaling: use A^-T.
                vx,vy = coords[2]-coords[0],coords[3]-coords[1]
                det = a*d-b*c
                if abs(det)<1e-12: raise ConversionError("Singular gradient matrix")
                nx,ny = (d*vx-b*vy)/det,(-c*vx+a*vy)/det
                denominator = nx*nx+ny*ny
                if denominator<1e-16: raise ConversionError("Degenerate gradient vector")
                scale = (vx*vx+vy*vy)/denominator
                end = (start[0]+nx*scale,start[1]+ny*scale)
            if math.dist(start,end)<1e-8: raise ConversionError("Degenerate gradient vector")
            key = (tuple(stops),start,end,radial,focus)
            if key not in gradient_cache:
                gradient_cache[key] = Gradient(f"PDF gradient {len(gradient_cache)+1}",tuple(stops),start,end,radial,focus)
            return gradient_cache[key]
        values = tuple(float(v) for v in values)
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
            raise ConversionError("Color components must be in [0, 1]")
        if isinstance(space, pikepdf.Array):
            if str(space[0]) == '/ICCBased':
                from .color_management import icc_to_rgb
                profile = space[1]
                if not isinstance(profile,pikepdf.Stream):raise ConversionError('Invalid ICC profile stream')
                model = {1:'Gray',3:'RGB',4:'CMYK'}.get(int(profile.get('/N',0)))
                if model is None or len(values) != {'Gray':1,'RGB':3,'CMYK':4}[model]:
                    raise ConversionError('Invalid ICC color components')
                if list(profile.get('/Range',[0,1]*len(values))) != [0,1]*len(values):
                    raise ConversionError('Nonstandard ICC component Range is unsupported')
                pixel = bytes(round(v*255) for v in values)
                data = profile.read_bytes()
                rgb = icc_to_rgb(pixel,1,1,model,data,state.rendering_intent)
                if 'ICC vector colors converted to sRGB using LittleCMS' not in conversions:
                    conversions.append('ICC vector colors converted to sRGB using LittleCMS')
                return Color('RGB',tuple(v/255 for v in rgb),None,data,model,values)
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
    outlined_strokes = 0
    approximated_strokes = 0

    def show_text(string):
        nonlocal text_matrix,outlined_glyphs,outlined_strokes,approximated_strokes
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
                if paint!='fill' and state.width==0:raise ConversionError('Hairline text strokes are unsupported')
                nonuniform=paint!='fill' and (not math.isclose(stroke_scale,math.hypot(c,d),abs_tol=1e-7) or not math.isclose(a*c+b*d,0,abs_tol=1e-7))
                outlines=outline_straight_strokes(glyph_paths,state) if nonuniform else None
                if nonuniform:
                    outlined_strokes+=len(glyph_paths)
                    approximated_strokes+=sum(any(op=='C' for op,_ in p.commands) for p in glyph_paths)
                paints = ('fill','stroke') if paint=='both' and (nonuniform or isinstance(state.fill,Gradient) or state.fill_alpha!=state.stroke_alpha) else (paint,)
                knockout_split = len(paints)==2 and (state.fill_alpha!=1 or state.stroke_alpha!=1 or state.blend_mode!='Normal')
                if knockout_split:
                    boundary_state = copy(state);boundary_state.layer = active_layer
                    boundary_state.fill_alpha = boundary_state.stroke_alpha = 1
                    boundary_state.blend_mode = 'Normal'
                    items.append(GroupBoundary(boundary_state,True,False,None,True))
                for paint_mode in paints:
                    glyph_state = copy(state);glyph_state.layer = active_layer
                    if nonuniform and paint_mode=='stroke':
                        if not outlines:continue
                        glyph_state.fill=state.stroke;glyph_state.fill_alpha=state.stroke_alpha;glyph_state.fill_overprint=state.stroke_overprint
                        item=PaintedPath(outlines,glyph_state,'fill',False,1)
                    else:item = PaintedPath(glyph_paths,glyph_state,paint_mode,False,stroke_scale)
                    painted.append(item);items.append(item)
                if knockout_split:
                    items.append(GroupBoundary(boundary_state,False,False,None,True))
            if glyph_paths and mode!=3: outlined_glyphs += 1
            advance = (width*state.font_size/1000+state.char_spacing+(state.word_spacing if code==32 and not font.cid else 0))*state.horizontal_scale
            text_matrix = compose(text_matrix,(1,0,0,1,advance,0))

    def set_rendering_intent(value):
        if str(value) not in RENDERING_INTENTS:raise ConversionError('Invalid rendering intent')
        state.rendering_intent = RENDERING_INTENTS[str(value)]
        from .color_management import icc_to_rgb
        for attribute in ('fill','stroke'):
            current = getattr(state,attribute)
            if isinstance(current,Color) and current.icc_profile is not None:
                rgb = icc_to_rgb(bytes(round(v*255) for v in current.icc_values),1,1,
                                 current.icc_model,current.icc_profile,state.rendering_intent)
                setattr(state,attribute,Color('RGB',tuple(v/255 for v in rgb),None,
                                             current.icc_profile,current.icc_model,current.icc_values))

    marked = 0
    for op,args,resources in content_instructions(page, resources):
        spaces = resources.get('/ColorSpace', {})
        if op == '_form_begin':
            if paths or pending_clip is not None: raise ConversionError("Form within an unfinished path")
            obj = args[0]
            matrix = tuple(map(float,obj.get('/Matrix',IDENTITY)))
            bounds = tuple(map(float,obj.get('/BBox', [])))
            if len(matrix)!=6 or len(bounds)!=4 or not all(math.isfinite(v) for v in (*matrix,*bounds)):
                raise ConversionError("Invalid Form matrix or BBox")
            # PDF rectangles may specify opposite corners in either order.
            # Scribus outlined glyph Forms commonly use descending Y bounds.
            bounds=(min(bounds[0],bounds[2]),min(bounds[1],bounds[3]),max(bounds[0],bounds[2]),max(bounds[1],bounds[3]))
            transparency = obj.get('/Group')
            scopes.append((copy(state),pattern_base,len(stack),marked,transparency))
            if transparency is not None:
                space = transparency.get('/CS')
                if space is not None and str(space) not in ('/DeviceRGB','/DeviceCMYK'):
                    raise ConversionError('Unsupported Form transparency group color space')
                boundary_state = copy(state);boundary_state.layer = active_layer
                group_model = {'/DeviceRGB':'RGB','/DeviceCMYK':'CMYK'}.get(str(space))
                items.append(GroupBoundary(boundary_state,True,bool(transparency.get('/I',False)),group_model,bool(transparency.get('/K',False))))
            state = copy(state)
            if transparency is not None:
                state.fill_alpha = state.stroke_alpha = 1
                state.blend_mode = 'Normal'
            state.matrix = compose(state.matrix,matrix)
            pattern_base = state.matrix
            pts = [point(state.matrix,x,y) for x,y in ((bounds[0],bounds[1]),(bounds[2],bounds[1]),(bounds[2],bounds[3]),(bounds[0],bounds[3]))]
            state.clips += (Clip([Subpath([('m' if i==0 else 'L',p) for i,p in enumerate(pts)],True)],False),)
            continue
        if op == '_form_end':
            previous,base,depth,previous_marked,transparency = scopes.pop()
            if paths or pending_clip is not None or len(stack)!=depth or marked!=previous_marked:
                raise ConversionError("Unbalanced Form graphics state")
            if transparency is not None:
                boundary_state = copy(previous);boundary_state.layer = active_layer
                items.append(GroupBoundary(boundary_state,False,bool(transparency.get('/I',False)),None,bool(transparency.get('/K',False))))
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
                if key==(0,0):
                    # Direct dictionaries all share objgen (0,0), so don't cache
                    # them together or reuse another Form's font definition.
                    state.text_font = OutlineFont(font)
                else:
                    if key not in font_cache: font_cache[key] = OutlineFont(font)
                    state.text_font = font_cache[key]
                state.font_size = float(args[1])
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
                if key == '/RI':
                    set_rendering_intent(value)
                    continue
                if key == '/FL':
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
                image_space = image.get('/ColorSpace')
                default = {'/DeviceRGB':'/DefaultRGB','/DeviceCMYK':'/DefaultCMYK','/DeviceGray':'/DefaultGray'}.get(str(image_space))
                if default and default in resources.get('/ColorSpace',{}):
                    image_space = resources.ColorSpace[default]
                    if not isinstance(image_space,pikepdf.Array) or str(image_space[0]) != '/ICCBased':
                        raise ConversionError('Unsupported default image color space replacement')
                raster = read_image(image,image_state,color_space=image_space)
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
                nonuniform = paint != 'fill' and (not math.isclose(scale,math.hypot(c,d),abs_tol=1e-7) or not math.isclose(a*c+b*d,0,abs_tol=1e-7))
                outlines = outline_straight_strokes(paths,state) if nonuniform else None
                if nonuniform:
                    outlined_strokes += len(paths)
                    approximated_strokes += sum(any(op=='C' for op,_ in path.commands) for path in paths)
                if any(len(path.commands)>8191 for path in paths):
                    raise ConversionError("A subpath exceeds Illustrator's 8191-segment limit")
                paints = ('fill','stroke') if paint == 'both' and (nonuniform or isinstance(state.fill,Gradient) or state.fill_alpha != state.stroke_alpha) else (paint,)
                knockout_split = len(paints)==2 and (state.fill_alpha!=1 or state.stroke_alpha!=1 or state.blend_mode!='Normal')
                if knockout_split:
                    boundary_state = copy(state);boundary_state.layer = active_layer
                    boundary_state.fill_alpha = boundary_state.stroke_alpha = 1
                    boundary_state.blend_mode = 'Normal'
                    items.append(GroupBoundary(boundary_state,True,False,None,True))
                for mode in paints:
                    paint_state = copy(state);paint_state.layer = active_layer
                    if nonuniform and mode=='stroke':
                        if not outlines: continue
                        paint_state.fill=state.stroke;paint_state.fill_alpha=state.stroke_alpha
                        paint_state.fill_overprint=state.stroke_overprint
                        item = PaintedPath(outlines,paint_state,'fill',False,1)
                    else:
                        item = PaintedPath(paths, paint_state, mode, "*" in op, scale)
                    painted.append(item);items.append(item)
                if knockout_split:
                    items.append(GroupBoundary(boundary_state,False,False,None,True))
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
                if any(scope[4] is not None for scope in scopes) and selected != active_layer:
                    raise ConversionError('Layer changes inside transparency groups are unsupported')
                if active_layer is not None and selected != active_layer:
                    raise ConversionError("Nested different PDF layer visibility conditions are unsupported")
                active_layer = selected
            marked += 1
        elif op == 'EMC':
            if marked<=0: raise ConversionError("Unbalanced marked content")
            if paths or pending_clip is not None: raise ConversionError("Layer boundary within unfinished path")
            active_layer = marked_layers.pop()
            marked -= 1
        elif op == 'ri':
            set_rendering_intent(args[0])
        elif op in ('MP','DP','i'):
            pass  # Structural tags and rendering intent do not change path geometry.
        else:
            raise ConversionError(f"Unsupported PDF operator '{op}'. No output was written. See README for supported paths, images and transparency.")
    if stack or paths or pending_clip is not None or marked or scopes or text_active: raise ConversionError("Unbalanced or unfinished PDF graphics")
    models = set()
    for item in items:
        if isinstance(item,GroupBoundary): continue
        if isinstance(item,Raster): models.add(item.model)
        else:
            colors = ([item.state.fill] if item.paint=='fill' else [item.state.stroke] if item.paint=='stroke' else [item.state.fill,item.state.stroke])
            for value in colors:
                models.update(c.model for _,c in value.stops) if isinstance(value,Gradient) else models.add(value.model)
    color_model = ('RGB' if str(group.get('/CS')) == '/DeviceRGB' else 'CMYK') if group is not None else ('RGB' if 'RGB' in models and not models.intersection({'CMYK','Spot'}) else 'CMYK')
    if any(isinstance(i,GroupBoundary) and i.color_model is not None and i.color_model != color_model for i in items):
        raise ConversionError('Transparency group color space differs from AI document color space')
    conversions.extend(dict.fromkeys(i.color_conversion for i in images if i.color_conversion))
    if color_model == 'RGB':
        from .color_management import cmyk_to_rgb
        for image in images:
            if image.model == 'CMYK':
                image.pixels = cmyk_to_rgb(image.pixels,image.width,image.height)
                image.model = 'RGB'
                conversions.append('DeviceCMYK image normalized to PDF renderer RGB before AI serialization')
    return Drawing(box, painted, list(used_spots.values()), operators, images, items, color_model, list(layer_map.values()),outlined_glyphs,outlined_strokes,approximated_strokes,conversions)
