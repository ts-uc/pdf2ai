"""Outline embedded TrueType/OpenType/CFF fonts and standard PDF Latin fonts."""
from io import BytesIO
import pikepdf
from fontTools.ttLib import TTFont
from fontTools.cffLib import CFFFontSet
from fontTools.pens.basePen import BasePen
from fontTools.encodings.StandardEncoding import StandardEncoding
from fontTools.agl import UV2AGL, toUnicode
from .vector import ConversionError, Subpath, point


class OutlinePen(BasePen):
    def __init__(self,glyphs):
        super().__init__(glyphs);self.paths=[]
    def _moveTo(self,p):self.paths.append(Subpath([('m',tuple(p))]))
    def _lineTo(self,p):self.paths[-1].commands.append(('L',tuple(p)))
    def _curveToOne(self,a,b,c):self.paths[-1].commands.append(('C',(*a,*b,*c)))
    def _qCurveToOne(self,control,end):
        start=self._getCurrentPoint()
        a=tuple(start[i]+2*(control[i]-start[i])/3 for i in (0,1))
        b=tuple(end[i]+2*(control[i]-end[i])/3 for i in (0,1))
        self._curveToOne(a,b,end)
    def _closePath(self):self.paths[-1].closed=True
    def _endPath(self):pass


class OutlineFont:
    def __init__(self,font):
        self.font=font
        self.cid=str(font.get('/Subtype'))=='/Type0'
        self.base=font.DescendantFonts[0] if self.cid else font
        if self.cid and str(font.get('/Encoding'))!='/Identity-H':
            raise ConversionError('Only Identity-H CID text encoding is supported natively')
        descriptor=self.base.get('/FontDescriptor',{})
        stream=descriptor.get('/FontFile2',descriptor.get('/FontFile3'))
        data=stream.read_bytes() if stream is not None else None
        subtype=str(stream.get('/Subtype')) if stream is not None else None
        self.cmap={};self.ttf=None;self.cff=None;self.cache={}
        if data is None:
            import pymupdf
            name=str(font.get('/BaseFont',''))[1:]
            names={'Helvetica','Helvetica-Bold','Helvetica-Oblique','Helvetica-BoldOblique',
                   'Times-Roman','Times-Bold','Times-Italic','Times-BoldItalic',
                   'Courier','Courier-Bold','Courier-Oblique','Courier-BoldOblique'}
            if self.cid or name not in names:
                raise ConversionError('Font program is not embedded; native outlining cannot substitute it')
            data=pymupdf.Font(fontname=name).buffer;subtype='/Type1C'
        try:
            if subtype in ('/Type1C','/CIDFontType0C'):
                self.cff=CFFFontSet();self.cff.decompile(BytesIO(data),None)
                top=self.cff.topDictIndex[0]
                matrix=list(getattr(top,'FontMatrix',[0.001,0,0,0.001,0,0]))
                if matrix[1:]!=[0,0,matrix[0],0,0] or matrix[0]<=0:
                    raise ConversionError('Unsupported CFF font matrix')
                self.units=1/matrix[0];self.glyphs=top.CharStrings;self.order=list(top.charset)
            else:
                self.ttf=TTFont(BytesIO(data),lazy=False)
                self.units=self.ttf['head'].unitsPerEm;self.glyphs=self.ttf.getGlyphSet()
                self.order=self.ttf.getGlyphOrder();self.cmap=self.ttf.getBestCmap() or {}
        except ConversionError:raise
        except Exception as exc:raise ConversionError(f'Unable to decode embedded font: {exc}') from exc
        if not 0<self.units<=65536:raise ConversionError('Invalid font units per em')
        self.encoding=font.get('/Encoding')
        self.differences={}
        if isinstance(self.encoding,pikepdf.Dictionary):
            code=None
            for value in self.encoding.get('/Differences',[]):
                if isinstance(value,pikepdf.Name):
                    if code is None:raise ConversionError('Invalid font encoding Differences')
                    self.differences[code]=str(value)[1:];code+=1
                else:code=int(value)
            self.encoding=self.encoding.get('/BaseEncoding',pikepdf.Name.StandardEncoding)
        self.cid_widths={}
        if self.cid:
            widths=list(self.base.get('/W',[]));i=0
            while i<len(widths):
                first=int(widths[i]);second=widths[i+1];i+=2
                if isinstance(second,pikepdf.Array):
                    for j,width in enumerate(second):self.cid_widths[first+j]=float(width)
                else:
                    last=int(second);width=float(widths[i]);i+=1
                    if last<first or last-first>65536:raise ConversionError('Invalid CID width range')
                    self.cid_widths.update((code,width) for code in range(first,last+1))

    def glyph_name(self,code):
        if self.cid:
            mapping=self.base.get('/CIDToGIDMap',pikepdf.Name.Identity)
            if isinstance(mapping,pikepdf.Stream):
                raw=mapping.read_bytes();start=code*2
                if start+2>len(raw):raise ConversionError('CID glyph map is incomplete')
                index=int.from_bytes(raw[start:start+2],'big')
            elif str(mapping)=='/Identity':index=code
            else:raise ConversionError('Unsupported CID glyph map')
            if str(self.base.get('/Subtype'))=='/CIDFontType0':
                name=f'cid{code:05d}'
                if name in self.glyphs:return name
                raise ConversionError('Unsupported CFF CID character mapping')
            if index>=len(self.order):raise ConversionError('CID glyph index is out of range')
            return self.order[index]
        if code in self.differences:
            name=self.differences[code]
            if name in self.glyphs:return name
            unicode=toUnicode(name)
            if len(unicode)==1 and ord(unicode) in self.cmap:return self.cmap[ord(unicode)]
            raise ConversionError(f'Font lacks encoded glyph {name}')
        encoding=str(self.encoding) if self.encoding is not None else '/StandardEncoding'
        if encoding=='/StandardEncoding':
            name=StandardEncoding[code]
            if name in self.glyphs:return name
            unicode=toUnicode(name)
            if len(unicode)==1 and ord(unicode) in self.cmap:return self.cmap[ord(unicode)]
        elif encoding in ('/WinAnsiEncoding','/MacRomanEncoding'):
            try:unicode=bytes([code]).decode('cp1252' if encoding=='/WinAnsiEncoding' else 'mac_roman')
            except UnicodeDecodeError:raise ConversionError('Undefined font character code')
            if ord(unicode) in self.cmap:return self.cmap[ord(unicode)]
            name=UV2AGL.get(ord(unicode))
            if name in self.glyphs:return name
        else:raise ConversionError('Unsupported simple font encoding')
        if code in self.cmap:return self.cmap[code]
        if code+0xF000 in self.cmap:return self.cmap[code+0xF000]
        raise ConversionError(f'Font lacks character code {code}')

    def codes(self,string):
        raw=bytes(string)
        if self.cid:
            if len(raw)%2:raise ConversionError('Invalid Identity-H text byte length')
            return [int.from_bytes(raw[i:i+2],'big') for i in range(0,len(raw),2)]
        return list(raw)

    def outlines(self,code,matrix):
        name=self.glyph_name(code)
        if name not in self.cache:
            pen=OutlinePen(self.glyphs);self.glyphs[name].draw(pen);self.cache[name]=pen.paths
        result=[]
        for path in self.cache[name]:
            commands=[]
            for op,coords in path.commands:
                commands.append((op,tuple(v for i in range(0,len(coords),2) for v in point(matrix,*coords[i:i+2]))))
            result.append(Subpath(commands,path.closed))
        if self.cid:width=self.cid_widths.get(code,float(self.base.get('/DW',1000)))
        else:
            index=code-int(self.base.get('/FirstChar',0));widths=self.base.get('/Widths',[])
            if 0<=index<len(widths):width=float(widths[index])
            elif self.ttf is not None:width=self.ttf['hmtx'][name][0]*1000/self.units
            else:width=float(self.glyphs[name].width)*1000/self.units
        return result,width
