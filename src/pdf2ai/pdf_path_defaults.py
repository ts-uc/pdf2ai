"""Match Adobe's local PDF fill coordinates without quantizing editable AI paths."""
import math
from decimal import Decimal, ROUND_HALF_UP

import pikepdf

from .vector import IDENTITY, compose, point


PATH_OPERATORS = {'m', 'l', 'c', 'v', 'y', 're', 'h'}


def round_pdf_coordinate(value, places):
    """Use decimal half-away rounding, avoiding Python's round-to-even ties."""
    if (float(value) * 10**places).is_integer():
        return value
    return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP))


def inverse(matrix):
    a,b,c,d,e,f = matrix
    determinant = a*d-b*c
    if abs(determinant) < 1e-10 or max(abs(v) for v in matrix[:4])>100:
        return None
    result = (d/determinant,-b/determinant,-c/determinant,a/determinant,
              (c*f-d*e)/determinant,(b*e-a*f)/determinant)
    return result if (all(math.isfinite(v) and abs(v)<1e8 for v in result)
                      and max(abs(v) for v in result[:4])<=100) else None


def instruction(op, values=()):
    # PDF numbers must not use exponential notation.
    from decimal import Decimal
    return pikepdf.ContentStreamInstruction([Decimal(f'{v:.12f}') for v in values],pikepdf.Operator(op))


def fill_commands(path, matrix, box):
    commands=[]
    current=start=None
    for args,operator in path:
        op=str(operator);values=tuple(float(v) for v in args)
        if op=='h':
            commands.append(('h',()));current=start
            continue
        if op=='re':
            x,y,w,h=values
            coords=[point(matrix,X,Y) for X,Y in ((x,y),(x+w,y),(x+w,y+h),(x,y+h))]
            commands.extend([('m',coords[0]),*(('l',p) for p in coords[1:]),('h',())])
            current=start=coords[0]
            continue
        coords=tuple(v for i in range(0,len(values),2) for v in point(matrix,*values[i:i+2]))
        if op=='m':
            start=coords
        elif op=='v':
            if current is None:return None
            coords=(*current,*coords);op='c'
        elif op=='y':
            coords=(*coords,*coords[-2:]);op='c'
        commands.append((op,coords));current=coords[-2:]
    if not commands or commands[0][0]!='m':return None
    # Adobe trims a solid rectangular background covering the artboard to the
    # artboard rectangle itself. This gives its fractional edge actual coverage.
    vertices=[coords for op,coords in commands if op in ('m','l')]
    trimmed=False
    if len(vertices)==5 and vertices[-1]==vertices[0]:vertices=vertices[:-1]
    if (len(vertices)==4 and sum(op=='m' for op,_ in commands)==1
            and all(op!='h' for op,_ in commands[:-1])
            and all(op in ('m','l','h') for op,_ in commands)
            and all(a[0]==b[0] or a[1]==b[1] for a,b in zip(vertices,vertices[1:]+vertices[:1]))):
        xs,ys=[p[0] for p in vertices],[p[1] for p in vertices]
        x0,y0,x1,y1=box
        if min(xs)<=x0 and min(ys)<=y0 and max(xs)>=x1 and max(ys)>=y1:
            trimmed=(min(xs),min(ys),max(xs),max(ys))!=tuple(box)
            commands=[('m',(x0,y0)),('l',(x1,y0)),('l',(x1,y1)),('l',(x0,y1)),('h',())]
    if any(not math.isfinite(v) or abs(v)>16000 for _,coords in commands for v in coords):
        return None
    origin=commands[0][1]
    rounded_origin=tuple(round_pdf_coordinate(v,4) for v in origin)
    rounded_commands=[]
    # Do not round a subpath whose thin dimension or tiny distinct anchors
    # would disappear on the 0.001pt grid.
    protected=set()
    starts=[i for i,(op,_) in enumerate(commands) if op=='m']+[len(commands)]
    ranges=list(zip(starts,starts[1:]))
    parents=list(range(len(ranges)))
    def root(index):
        while parents[index]!=index:
            parents[index]=parents[parents[index]]
            index=parents[index]
        return index
    anchor_cells={}
    colliding=set()
    for subpath,(first,last) in enumerate(ranges):
        points=[coords[i:i+2] for _,coords in commands[first:last] for i in range(0,len(coords),2)]
        anchors=[coords[-2:] for _,coords in commands[first:last] if coords]
        rounded=[tuple(round_pdf_coordinate(v-origin[i],3) for i,v in enumerate(p)) for p in anchors]
        for anchor,cell in zip(anchors,rounded):
            existing=anchor_cells.get(cell)
            if existing is None:
                anchor_cells[cell]=(anchor,subpath)
            else:
                original,owner=existing
                parents[root(subpath)]=root(owner)
                if original!=anchor:
                    colliding.add(subpath)
        narrow=any(0 < max(p[i] for p in points)-min(p[i] for p in points)<.001 for i in (0,1))
        collapse=any(a!=b and ra==rb for a,b,ra,rb in zip(anchors,anchors[1:]+anchors[:1],rounded,rounded[1:]+rounded[:1]))
        if narrow or collapse:colliding.add(subpath)
    # Close contours or nonadjacent anchors can merge even when each contour's
    # own width and consecutive segments are large. Preserve every involved
    # subpath, including another owner of an exactly shared anchor.
    protected_roots={root(subpath) for subpath in colliding}
    for subpath,(first,last) in enumerate(ranges):
        if root(subpath) in protected_roots:protected.update(range(first,last))
    for index,(op,coords) in enumerate(commands):
        if not coords:
            rounded_commands.append((op,()));continue
        relative=tuple(v-origin[i%2] for i,v in enumerate(coords))
        rounded=relative if index in protected else tuple(round_pdf_coordinate(v,3) for v in relative)
        rounded_commands.append((op,rounded))
    if not trimmed and all(abs(v-(rounded[i]+rounded_origin[i%2]))<1e-10
                           for (_,coords),(_,rounded) in zip(commands,rounded_commands)
                           for i,v in enumerate(coords)):
        return None
    undo=inverse(matrix)
    if undo is None:return None
    return [instruction('q'),instruction('cm',undo),
            instruction('cm',(1,0,0,1,*rounded_origin)),
            *(instruction(op,coords) for op,coords in rounded_commands)]


def align_pdf_fill_paths(page):
    """Normalize contiguous fill paths only; keep strokes, clips and resources.

    The caller restricts this to opaque unprofiled CMYK/spot path pages. Private
    AI geometry is never modified. Rotation/UserUnit and inline images are left
    to the original PDF representation.
    """
    if int(page.obj.get('/Rotate',0))%360 or float(page.obj.get('/UserUnit',1))!=1:
        return 0
    instructions=list(pikepdf.parse_content_stream(page))
    if any(not hasattr(item,'operator') or str(item.operator)=='INLINE IMAGE'
           for item in instructions):return 0
    box=tuple(float(v) for v in page.obj.get('/CropBox',page.MediaBox))
    matrix=IDENTITY;stack=[];pending=[];result=[];changed=0;unfinished=False
    for item in instructions:
        args,operator=item;op=str(operator)
        if op in PATH_OPERATORS:
            pending.append(item);continue
        if pending:
            normalized=fill_commands(pending,matrix,box) if not unfinished and op in ('f','f*','F') else None
            if normalized is not None:
                result.extend(normalized);result.append(item);result.append(instruction('Q'))
                pending=[];changed+=1;continue
            result.extend(pending);pending=[]
            unfinished=True
        result.append(item)
        if op in ('f','f*','F','S','s','B','B*','b','b*','n'):
            unfinished=False
        if op=='q':stack.append(matrix)
        elif op=='Q':
            if not stack:return 0
            matrix=stack.pop()
        elif op=='cm':matrix=compose(matrix,tuple(float(v) for v in args))
    result.extend(pending)
    if stack:return 0
    if changed:
        # A Contents stream can belong to several pages; never rewrite it in
        # place. contents_add creates an owned stream which replaces this page.
        page.contents_add(pikepdf.unparse_content_stream(result),prepend=True)
        page.obj.Contents=page.obj.Contents[0]
    return changed
