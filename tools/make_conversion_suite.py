"""全変換機能を1冊のPDFで検証するための生成ツール。

既存のテスト・サンプルに依存せず、図形、画像、フォント、レイヤー、
グラデーション、ページ属性と自動画像化用のページを生成します。
実行例: python tools/make_conversion_suite.py
出力: sample/conversion_native.pdf（1ページ）、conversion_pages.pdf、
conversion_fallback.pdf。図版に検証項目を記載。期待結果はconversion_suite.jsonに収録。
"""
from pathlib import Path
from io import BytesIO
import json
import tempfile
import sys
import pikepdf
import pymupdf
from PIL import Image
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from pdf2ai.vector import BLEND_MODES
from pdf2ai.native import convert,read_private

def feature_pdf(path):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(600,600))
    page.obj.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
    function=pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[1,1,1],C1=[1,0,0],N=1)
    radial=pikepdf.Dictionary(ShadingType=3,ColorSpace=pikepdf.Name.DeviceRGB,
                             Coords=[100,460,0,100,460,70],Extend=[True,True],Function=function)
    # The nested form has its own resource named Alpha, shadowing the page's.
    inner=pdf.make_stream(b'/Alpha gs 0 0 1 rg -20 -20 100 100 re f')
    inner.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject,Subtype=pikepdf.Name.Form,
                                  BBox=[0,0,60,60],Matrix=[1,0,0,1,5,5],
                                  Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(Alpha=pikepdf.Dictionary(ca=0.5)))))
    outer=pdf.make_stream(b'q 1 0 0 1 10 10 cm /Child Do Q 1 0 0 rg 0 0 10 10 re f')
    outer.update(pikepdf.Dictionary(Type=pikepdf.Name.XObject,Subtype=pikepdf.Name.Form,
                                  BBox=[0,0,80,80],Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Child=inner))))
    gs=pikepdf.Dictionary(Alpha=pikepdf.Dictionary(ca=0.2),Split=pikepdf.Dictionary(ca=0.5,CA=1,LW=4))
    content=['q 20 380 160 160 re W n /Radial sh Q',
             'q 230 400 120 120 re 260 430 60 60 re W* n 0 1 0 rg 210 380 160 160 re f Q',
             'q 1 0 0 1 410 410 cm /Form Do Q',
             'q /Split gs 1 0 0 rg 0 0 1 RG 420 320 80 50 re B Q']
    for i,mode in enumerate(BLEND_MODES):
        x=20+(i%5)*110;y=280-(i//5)*80
        gs[f'/{mode}']=pikepdf.Dictionary(BM=pikepdf.Name('/'+mode))
        content.append(f'q 0.2 0.6 0.8 rg {x} {y} 80 50 re f /{mode} gs 0.9 0.3 0.1 rg {x+20} {y+10} 80 50 re f Q')
    page.obj.Resources=pikepdf.Dictionary(Shading=pikepdf.Dictionary(Radial=radial),XObject=pikepdf.Dictionary(Form=outer),ExtGState=gs)
    page.obj.Contents=pdf.make_stream('\n'.join(content).encode());pdf.save(path)

def layer_pdf(path, *, interleaved=False, membership=False):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,100))
    groups=[pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.OCG,Name=n)) for n in ('背景','非表示','文字と図形','空レイヤー')]
    back,hidden,front,empty=groups
    pdf.Root.OCProperties=pikepdf.Dictionary(OCGs=groups,D=pikepdf.Dictionary(BaseState=pikepdf.Name.ON,OFF=[hidden],Locked=[back],Order=list(reversed(groups))))
    prop=pikepdf.Dictionary(Back=back,Hidden=hidden,Front=front)
    if membership: prop.Front=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.OCMD,OCGs=[back,front],P=pikepdf.Name.AnyOn))
    form=pdf.make_stream(b'0 1 0 rg 60 20 70 60 re f')
    form.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Form,BBox=[0,0,200,100],OC=front,Resources=pikepdf.Dictionary()))
    page.obj.Resources=pikepdf.Dictionary(Properties=prop,XObject=pikepdf.Dictionary(F=form))
    contents=b'/OC /Back BDC q 1 0 0 rg 10 10 180 80 re f Q EMC /OC /Hidden BDC 0 0 1 rg 30 20 140 60 re f EMC /OC /Front BDC /Span BMC 1 1 0 rg 70 30 50 40 re f EMC EMC /F Do'
    if interleaved:contents+=b' /OC /Back BDC 0 0 0 rg 80 40 20 20 re f EMC'
    page.obj.Contents=pdf.make_stream(contents);pdf.save(path)

def true_type_pdf(path):
    builder=FontBuilder(1000,isTTF=True);builder.setupGlyphOrder(['.notdef','space','A','B'])
    glyphs={}
    for name in ('.notdef','space','A','B'):
        pen=TTGlyphPen(None)
        if name in ('A','B'):
            pen.moveTo((0,0));pen.lineTo((500,0));pen.lineTo((500,700));pen.qCurveTo((250,900),(0,700));pen.closePath()
        glyphs[name]=pen.glyph()
    builder.setupGlyf(glyphs);builder.setupHorizontalMetrics({n:(600,0) for n in glyphs})
    builder.setupHorizontalHeader(ascent=800,descent=-200);builder.setupCharacterMap({32:'space',65:'A',66:'B'})
    builder.setupNameTable({'familyName':'Fixture','styleName':'Regular','uniqueFontIdentifier':'Fixture','fullName':'Fixture','psName':'Fixture'})
    builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
    builder.setupPost();buffer=BytesIO();builder.save(buffer)
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,100))
    program=pdf.make_stream(buffer.getvalue())
    descriptor=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.FontDescriptor,FontName=pikepdf.Name.Fixture,Flags=32,FontBBox=[0,0,500,700],ItalicAngle=0,Ascent=800,Descent=-200,CapHeight=700,StemV=80,FontFile2=program))
    mapping=bytearray(134);mapping[130:132]=b'\0\2';mapping[132:134]=b'\0\3'
    descendant=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.CIDFontType2,BaseFont=pikepdf.Name.Fixture,CIDSystemInfo=pikepdf.Dictionary(Registry=pikepdf.String('Adobe'),Ordering=pikepdf.String('Identity'),Supplement=0),FontDescriptor=descriptor,CIDToGIDMap=pdf.make_stream(bytes(mapping)),W=[65,[600,600]],DW=600))
    font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type0,BaseFont=pikepdf.Name.Fixture,Encoding=pikepdf.Name('/Identity-H'),DescendantFonts=[descendant]))
    layer=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.OCG,Name='Embedded text'))
    pdf.Root.OCProperties=pikepdf.Dictionary(OCGs=[layer],D=pikepdf.Dictionary(BaseState=pikepdf.Name.ON))
    page.obj.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F=font),Properties=pikepdf.Dictionary(L=layer))
    page.obj.Contents=pdf.make_stream(b'/OC /L BDC BT /F 20 Tf 1 0 0 1 20 50 Tm [<0041> -120 <0042>] TJ ET EMC')
    pdf.save(path)

A4=(595.276,841.89)


def document(content,resources=None,size=(400,240)):
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=size)
    page.obj.Resources=resources or pikepdf.Dictionary()
    page.obj.Contents=pdf.make_stream(content.encode('ascii'))
    return pdf


def label(pdf,title,detail=''):
    page=pdf.pages[0];r=page.obj.Resources
    r.Font=r.get('/Font',pikepdf.Dictionary())
    r.Font.SuiteLabel=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica))
    for key,font in list(r.Font.items()):
        if not font.is_indirect:r.Font[key]=pdf.make_indirect(font)
    x0,y0,x1,y1=map(float,page.MediaBox)
    y1+=45;page.MediaBox=[x0,y0,x1,y1]
    def escape(s):return s.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    commands=f'q 0 g BT /SuiteLabel 12 Tf 1 0 0 1 {x0+12} {y1-18} Tm ({escape(title)}) Tj 0 -16 Td /SuiteLabel 8 Tf ({escape(detail)}) Tj ET Q'
    old=page.obj.get('/Contents')
    streams=list(old) if isinstance(old,pikepdf.Array) else [old] if old is not None else []
    page.obj.Contents=pikepdf.Array([*streams,pdf.make_stream(commands.encode('ascii'))])


def function(first,last,n=1):
    return pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=first,C1=last,N=n)


def image_scene(kind):
    pdf=document('');page=pdf.pages[0]
    width,height=8,4;bits=8;space=pikepdf.Name.DeviceRGB
    rgb=bytes(v for y in range(height) for x in range(width) for v in (x*255//7,y*255//3,180))
    data=rgb;extra={};filters=None
    if kind.startswith('gray'):
        space=pikepdf.Name.DeviceGray;bits=int(kind[4:])
        if bits==16:data=b''.join((x*65535//7).to_bytes(2,'big') for y in range(height) for x in range(width))
        else:
            values=[x*((1<<bits)-1)//7 for x in range(width)]
            row=bytearray((width*bits+7)//8)
            for x,v in enumerate(values):row[x*bits//8]|=v << (8-bits-(x*bits%8))
            data=bytes(row)*height
    elif kind in ('cmyk','cmyk-soft-mask'):
        space=pikepdf.Name.DeviceCMYK;data=bytes(v for y in range(height) for x in range(width) for v in (x*255//7,y*255//3,0,0))
    elif kind=='rgb16':
        bits=16;data=b''.join((v*257).to_bytes(2,'big') for v in rgb)
    elif kind=='cmyk16':
        space=pikepdf.Name.DeviceCMYK;bits=16;data=b''.join((v*257).to_bytes(2,'big') for y in range(height) for x in range(width) for v in (x*255//7,y*255//3,0,0))
    elif kind=='indexed':
        space=pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name.DeviceRGB,1,pikepdf.String(b'\xff\0\0\0\0\xff')]);data=bytes(x%2 for y in range(height) for x in range(width))
    elif kind=='jpeg':
        buffer=BytesIO();Image.frombytes('RGB',(width,height),rgb).save(buffer,format='JPEG');data=buffer.getvalue();filters=pikepdf.Name.DCTDecode
    elif kind=='decode':extra['Decode']=[1,0,0,1,0,1]
    elif kind in ('stencil','stencil-inverted'):
        bits=1;data=b'\x55'*height;extra={'ImageMask':True,'Decode':[1,0] if kind.endswith('inverted') else [0,1]};space=None
    image=pdf.make_stream(data)
    image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=width,Height=height,BitsPerComponent=bits,**extra))
    if space is not None:image.ColorSpace=space
    if filters is not None:image.Filter=filters
    if kind in ('soft-mask','cmyk-soft-mask'):
        mask=pdf.make_stream(bytes(x*255//7 for y in range(height) for x in range(width)))
        mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=width,Height=height,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray));image.SMask=mask
    if kind=='hard-mask':
        mask=pdf.make_stream(b'\x55'*height);mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=width,Height=height,BitsPerComponent=1,ImageMask=True));image.Mask=mask
    if kind=='color-key':image.Mask=[0,0,0,0,180,180]
    page.obj.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image))
    page.obj.Contents=pdf.make_stream(b'q 0.85 g 30 40 320 120 re f 0 0.6 0 rg 30 40 320 120 re W n 300 20 -10 120 40 40 cm /Im Do Q')
    return pdf


def gradient_scene(model,radial=False,exponent=1,stitch=False,pattern=False):
    components={'RGB':([0,0,1],[1,0,0]),'CMYK':([1,0,0,0],[0,1,0,0]),'Gray':([0],[1])}
    first,last=components[model];fn=function(first,last,exponent)
    if stitch:
        middle=[(a+b)/2 for a,b in zip(first,last)]
        fn=pikepdf.Dictionary(FunctionType=3,Domain=[0,1],Functions=[function(first,middle),function(middle,last)],Bounds=[0.4],Encode=[0,1,0,1])
    shading=pikepdf.Dictionary(ShadingType=3 if radial else 2,ColorSpace=pikepdf.Name('/Device'+model),Coords=[200,100,0,200,100,75] if radial else [30,100,350,100],Extend=[True,True],Function=fn)
    if pattern:
        r=pikepdf.Dictionary(Pattern=pikepdf.Dictionary(P=pikepdf.Dictionary(PatternType=2,Matrix=[0,1,-1,0,300,-80],Shading=shading)))
        content='q /Pattern cs /P scn 30 30 320 130 re f Q'
    else:r=pikepdf.Dictionary(Shading=pikepdf.Dictionary(S=shading));content='q 30 30 320 130 re W n /S sh Q'
    return document(content,r)


def spot_scene():
    s2=pikepdf.Array([pikepdf.Name.Separation,pikepdf.Name('/Suite Spot Type2'),pikepdf.Name.DeviceCMYK,function([0,0,0,0],[0.2,0.8,0.4,0])])
    pdf=document('');calc=pdf.make_stream(b'{ dup 0.2 mul exch dup 0.8 mul exch dup 0.4 mul exch 0 mul }')
    calc.update(pikepdf.Dictionary(FunctionType=4,Domain=[0,1],Range=[0,1]*4))
    s4=pikepdf.Array([pikepdf.Name.Separation,pikepdf.Name('/Suite Spot Type4'),pikepdf.Name.DeviceCMYK,calc])
    pdf.pages[0].obj.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(S2=s2,S4=s4),ExtGState=pikepdf.Dictionary(OP=pikepdf.Dictionary(OP=True,op=True,OPM=1)))
    pdf.pages[0].obj.Contents=pdf.make_stream(b'/S2 cs 1 scn 20 100 70 60 re f 0.5 scn 100 100 70 60 re f 0.25 scn 180 100 70 60 re f /S4 cs 0.75 scn 280 100 70 60 re f q /OP gs /S2 CS 1 SCN 4 w 30 30 m 350 30 l S 0.1 0.7 0.2 0 k 30 40 150 40 re f Q')
    return pdf


def text_scene():
    names=['Helvetica','Helvetica-Bold','Helvetica-Oblique','Helvetica-BoldOblique','Times-Roman','Times-Bold','Times-Italic','Times-BoldItalic','Courier','Courier-Bold','Courier-Oblique','Courier-BoldOblique']
    fonts=pikepdf.Dictionary();content=[]
    for i,name in enumerate(names):
        fonts['/F'+str(i)]=pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name('/'+name))
        content.append(f'BT /F{i} 10 Tf 1 0 0 1 15 {175-i*13} Tm ({name}: ABC abc 0123) Tj ET')
    return document('\n'.join(content),pikepdf.Dictionary(Font=fonts))


def text_modes_scene():
    fonts=pikepdf.Dictionary(F=pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica,Encoding=pikepdf.Name.WinAnsiEncoding),M=pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.TimesRoman,Encoding=pikepdf.Name.MacRomanEncoding),D=pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica,Encoding=pikepdf.Dictionary(BaseEncoding=pikepdf.Name.StandardEncoding,Differences=[65,pikepdf.Name.B])))
    fonts.M.BaseFont=pikepdf.Name('/Times-Roman')
    commands=['0.3 w 0 0 0 RG 0 0.4 0.7 rg']
    for i in range(8):
        commands.append(f'q BT /F 26 Tf {i} Tr 1 0 0 1 {20+(i%4)*90} {140-(i//4)*70} Tm (Ab) Tj ET 0.9 0.5 0 rg 15 {120-(i//4)*70} 350 10 re f Q')
    commands+=['BT /F 12 Tf 1 Tc 3 Tw 85 Tz 2 Ts 14 TL 1 0 0 1 20 25 Tm [(A B) -120 (CD)] TJ (EF) \' 2 1 (GH) " ET', 'BT /M 10 Tf 1 0 0 1 20 10 Tm (MacRoman) Tj /D 10 Tf (AAA) Tj ET']
    return document('\n'.join(commands),pikepdf.Dictionary(Font=fonts))


def embedded_scene(path,kind):
    true_type_pdf(path);pdf=pikepdf.open(path)
    if kind=='cid':return pdf
    page=pdf.pages[0];cid=page.Resources.Font.F;descriptor=cid.DescendantFonts[0].FontDescriptor
    if kind=='cff':
        stream=pdf.make_stream(pymupdf.Font(fontname='Helvetica').buffer);stream.Subtype=pikepdf.Name.Type1C
        del descriptor['/FontFile2'];descriptor.FontFile3=stream
    elif kind=='opentype':
        stream=descriptor.FontFile2;stream.Subtype=pikepdf.Name.OpenType
        del descriptor['/FontFile2'];descriptor.FontFile3=stream
    page.Resources.Font.F=pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1 if kind=='cff' else pikepdf.Name.TrueType,BaseFont=pikepdf.Name.Fixture,FontDescriptor=descriptor,Encoding=pikepdf.Name.WinAnsiEncoding,FirstChar=65,LastChar=66,Widths=[600,600])
    page.Contents=pdf.make_stream(b'/OC /L BDC BT /F 20 Tf 1 0 0 1 20 50 Tm (AB) Tj ET EMC')
    return pdf


def add_groups(target,source,groups,off,locked):
    properties=source.Root.get('/OCProperties')
    if properties is None:return
    for group in properties.OCGs:groups.append(target.copy_foreign(group))
    default=properties.get('/D',{})
    for group in default.get('/OFF',[]):off.append(target.copy_foreign(group))
    for group in default.get('/Locked',[]):locked.append(target.copy_foreign(group))


def build_native(path,temporary):
    scenes=[]
    def add(title,pdf,features):
        label(pdf,f'{len(scenes)+1:02}. {title}',features);scenes.append((title,pdf,features))
    add('Paths, curves, fill rules, stroke styles',document('0.2 0.5 0.8 rg 20 40 80 100 re f 0.9 0.3 0.1 rg 120 40 90 110 re 140 60 50 70 re f* 0.1 g 230 40 m 280 190 320 0 370 140 c 360 20 260 20 v 220 120 230 40 y h f q 0.6 G 5 w 1 J 2 j 6 M [10 4 2 4] 3 d 30 20 m 200 20 l S Q 0 w 260 5 80 10 re f'), 'm l c v y h re; f f* S; dash, cap, join, miter, zero-width fill')
    add('Paint operators and nonzero clipping',document('0.3 0.5 0.8 rg 0.5 0 0 RG 2 w 20 40 m 80 140 l 100 40 l s 120 40 80 100 re B 140 60 40 60 re 150 70 20 40 re B* 220 40 m 280 140 l 300 40 l b 320 40 60 100 re 335 60 30 60 re b* q 30 30 80 80 re W n 0.8 0.1 0.4 rg 0 0 400 180 re F Q 0 0 m 1 1 l n'), 'F s B B* b b* n; W nonzero clip; fill + stroke')
    add('ExtGState line style',document('/Line gs 30 50 m 130 150 l 240 50 l S',pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(Line=pikepdf.Dictionary(LW=5,LC=2,LJ=1,ML=8,D=[[8,4],2])))), 'LW LC LJ ML D via gs')
    add('Transforms and graphics state',document('q 1.5 0 0 1.5 30 20 cm 3 w [5 2] 1 d 0 0 80 80 re S Q q 0.866 0.5 -0.5 0.866 230 50 cm 0 0.7 0.3 rg 0 0 100 90 re f Q q 1 0.2 0.4 0.8 260 30 cm 0.7 0 0.4 rg 0 0 90 90 re f Q'), 'q/Q; translation, uniform scale, rotation; shear/nonuniform fills')
    add('RGB, CMYK and gray',document('1 0 0 rg 20 40 60 100 re f 0 1 0 rg 90 40 60 100 re f 0 0 1 rg 160 40 60 100 re f 0 1 0 0 k 230 40 60 100 re f 0.5 g 300 40 60 100 re f'), 'DeviceRGB / DeviceCMYK / DeviceGray')
    add('Spot tints and overprint',spot_scene(),'Separation Type2/Type4; tint 25/50/75/100%; CMYK overprint OPM1')
    feature_pdf(temporary/'features.pdf');add('Forms, clipping, radial, all 16 blends',pikepdf.open(temporary/'features.pdf'),'nested resources, Form BBox/matrix; W*; fill/stroke opacity')
    for model in ['RGB','CMYK','Gray']:
        for radial in [False,True]:add(f'{model} '+('radial' if radial else 'axial')+' gradient',gradient_scene(model,radial), 'direct sh; extended ends; Type2 function')
    add('Nonlinear gradient',gradient_scene('RGB',exponent=2),'positive exponent N=2; editable adaptive stops')
    add('Stitched gradient',gradient_scene('CMYK',stitch=True),'continuous Type3 function / two Type2 functions')
    add('Rotated gradient pattern',gradient_scene('RGB',pattern=True),'PatternType2; rotation/translation matrix')
    for kind in ['gray1','gray2','gray4','gray8','gray16','cmyk','rgb16','cmyk16','indexed','jpeg','decode','soft-mask','cmyk-soft-mask','hard-mask','color-key','stencil','stencil-inverted','rgb']:
        add('Image: '+kind,image_scene(kind),'image transform + clipping; opaque/alpha as applicable')
    add('Standard Latin fonts',text_scene(),'12 standard fonts; automatic editable outlines')
    add('Text modes, encoding and spacing',text_modes_scene(),'Tr 0..7; TJ, quote, double quote; Tc Tw Tz Ts TL; WinAnsi/MacRoman/Differences')
    for kind in ['cid','ttf','opentype','cff']:add('Embedded font: '+kind,embedded_scene(temporary/'font.pdf',kind),'font program; PDF widths; CIDToGIDMap/Identity-H on CID; OCG layer')
    layer_pdf(temporary/'layers.pdf',interleaved=True)
    layerdoc=pikepdf.open(temporary/'layers.pdf');groups=layerdoc.Root.OCProperties.OCGs
    groups[0].Usage=pikepdf.Dictionary(Print=pikepdf.Dictionary(PrintState=pikepdf.Name.OFF))
    # Also place an image under an OCG attribute.
    im=layerdoc.make_stream(b'\xff\0\0');im.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=1,Height=1,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceRGB,OC=groups[2]))
    layerdoc.pages[0].Resources.XObject.Im=im
    layerdoc.pages[0].Contents=pikepdf.Array([layerdoc.pages[0].Contents,layerdoc.make_stream(b'q 15 0 0 15 170 15 cm /Im Do Q')])
    add('Layers and structural tags',layerdoc,'Japanese names; hidden, locked, nonprinting, empty; interleaved; Form/image OC')
    add('Text clip and rotation',document('q BT /F 80 Tf 0.866 0.5 -0.5 0.866 80 40 Tm 7 Tr (ABC) Tj ET 0 0.5 0.8 rg 0 0 400 180 re f Q',pikepdf.Dictionary(Font=pikepdf.Dictionary(F=pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica)))),'rotated text outline and text clipping')
    result=pikepdf.new();columns=4;cellw,cellh=430,290;rows=(len(scenes)+columns-1)//columns
    page=result.add_blank_page(page_size=(columns*cellw,rows*cellh+65));objects=pikepdf.Dictionary();content=[];ocgs=[];off=[];locked=[]
    for i,(title,pdf,features) in enumerate(scenes):
        source=pdf.pages[0];form=result.copy_foreign(source.as_form_xobject())
        if '/Group' in form:del form['/Group']
        objects['/Cell'+str(i)]=form
        box=list(map(float,source.MediaBox));scale=min((cellw-20)/(box[2]-box[0]),(cellh-20)/(box[3]-box[1]))
        x=(i%columns)*cellw+10;y=(rows-1-i//columns)*cellh+10
        content.append(f'q {scale} 0 0 {scale} {x-box[0]*scale} {y-box[1]*scale} cm /Cell{i} Do Q')
        add_groups(result,pdf,ocgs,off,locked)
    page.Resources=pikepdf.Dictionary(XObject=objects)
    page.obj.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
    page.Contents=result.make_stream('\n'.join(content).encode())
    result.Root.OCProperties=pikepdf.Dictionary(OCGs=ocgs,D=pikepdf.Dictionary(BaseState=pikepdf.Name.ON,OFF=off,Locked=locked))
    label(result,'NATIVE CONVERSION SUITE - one page',f'{len(scenes)} panels / vector mode expected / zoom in to inspect / outlines are not live text')
    result.save(path)
    return [{'panel':i+1,'title':title,'features':features} for i,(title,_,features) in enumerate(scenes)]


def build_pages(path):
    result=pikepdf.new();records=[]
    for rotation in [0,90,180,270]:
        pdf=document('1 0 0 rg 30 30 100 60 re f 0 0 1 rg 30 110 60 100 re f 3 w 30 30 m 200 250 l S',size=A4)
        label(pdf,f'PAGE ROTATION {rotation} / UserUnit 2','red horizontal rectangle, blue vertical rectangle; crop origin 10,20')
        page=pdf.pages[0];page.obj.Rotate=rotation;page.obj.UserUnit=2;page.obj.CropBox=[10,20,585,830]
        if rotation in (0,90):page.obj.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceCMYK if rotation==0 else pikepdf.Name.DeviceRGB)
        result.pages.extend(pdf.pages);records.append({'page':len(records)+1,'rotation':rotation,'user_unit':2,'expected_mode':'vector'})
    result.save(path);return records


def build_fallback(path,temporary):
    result=pikepdf.new();records=[];groups=[];off=[];locked=[]
    def add(title,pdf,reason):
        label(pdf,title,'RASTER FALLBACK expected / RGB image; no editable paths, spot separation or layers')
        result.pages.extend(pdf.pages);add_groups(result,pdf,groups,off,locked)
        records.append({'page':len(records)+1,'title':title,'reason_contains':reason,'expected_mode':'raster-fallback'})
    pdf=document('0.8 0 0 rg 30 50 150 100 re f 0 0.6 0 rg 120 80 150 100 re f',size=A4)
    pdf.pages[0].obj.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB,K=True)
    add('Knockout transparency group',pdf,'nonknockout')
    add('Hairline stroke',document('0 w 30 50 m 350 160 l S',size=A4),'hairline')
    add('Nonuniform stroke transform',document('q 2 0 0 1 30 50 cm 4 w 0 0 150 100 re S Q',size=A4),'Nonuniform')
    lab=pikepdf.Array([pikepdf.Name.Lab,pikepdf.Dictionary(WhitePoint=[0.9505,1,1.089])])
    add('Lab color space',document('/L cs 65 30 20 scn 30 50 300 120 re f',pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(L=lab)),size=A4),'Color components')
    pdf=document('0 0.5 1 rg 30 50 300 120 re f',size=A4)
    annotation=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,Subtype=pikepdf.Name.Square,Rect=[60,80,220,180],C=[1,0,0],Border=[0,0,4],F=4));pdf.pages[0].obj.Annots=[annotation]
    add('PDF annotation',pdf,'Annotations')
    pdf=document('');tile=pdf.make_stream(b'1 0 0 rg 0 0 5 5 re f')
    tile.update(pikepdf.Dictionary(Type=pikepdf.Name.Pattern,PatternType=1,PaintType=1,TilingType=1,BBox=[0,0,10,10],XStep=10,YStep=10,Resources=pikepdf.Dictionary()))
    pdf.pages[0].Resources=pikepdf.Dictionary(Pattern=pikepdf.Dictionary(P=tile));pdf.pages[0].Contents=pdf.make_stream(b'/Pattern cs /P scn 30 40 300 130 re f')
    pdf.pages[0].MediaBox=[0,0,*A4];add('Tiling pattern',pdf,'shading patterns')
    pdf=gradient_scene('RGB',radial=True);pdf.pages[0].Resources.Shading.S.Coords=[120,90,0,250,100,100];pdf.pages[0].MediaBox=[0,0,*A4]
    add('Nonconcentric radial gradient',pdf,'concentric')
    layer_pdf(temporary/'membership.pdf',membership=True);pdf=pikepdf.open(temporary/'membership.pdf');pdf.pages[0].MediaBox=[0,0,*A4]
    add('Complex layer membership (OCMD)',pdf,'OCMD')
    pdf=image_scene('stencil');pdf.pages[0].Resources.XObject.Im.Interpolate=True;pdf.pages[0].MediaBox=[0,0,*A4]
    add('Interpolated image stencil',pdf,'Interpolated')
    if groups:result.Root.OCProperties=pikepdf.Dictionary(OCGs=groups,D=pikepdf.Dictionary(BaseState=pikepdf.Name.ON,OFF=off,Locked=locked))
    result.save(path);return records


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify',action='store_true',help='全ページをAIに変換し、モード・編集ストリーム・PDF表示を検証')
    parser.add_argument('--verify-ghostscript',action='store_true',help='追加でGhostscript前処理を検証（Ghostscriptが必要）')
    args=parser.parse_args()
    sample=ROOT/'sample';sample.mkdir(exist_ok=True)
    output=ROOT/'output'/'conversion-suite';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='build-',dir=output) as directory:
        temporary=Path(directory)
        manifest={'native':build_native(sample/'conversion_native.pdf',temporary),'pages':build_pages(sample/'conversion_pages.pdf'),'fallback':build_fallback(sample/'conversion_fallback.pdf',temporary)}
    (sample/'conversion_suite.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Created 3 PDFs: native=1 page / {len(manifest["native"])} panels; pages=4 pages; fallback={len(manifest["fallback"])} pages')
    if args.verify or args.verify_ghostscript:
        reports=[]
        for name in ['native','pages','fallback']:
            source=sample/f'conversion_{name}.pdf'
            with pymupdf.open(source) as original:
                for i in range(len(original)):
                    dest=output/f'{name}-{i+1:02}.ai'
                    report=convert(source,dest,page_number=i+1,overwrite=True,raster_dpi=144)
                    expected='raster-fallback' if name=='fallback' else 'vector'
                    if report['conversion_mode']!=expected:raise AssertionError(f'{name} page {i+1}: {report}')
                    if name=='native':
                        if report['gradients']!=10 or report['images']!=17 or len(report['spots'])!=2 or report['outlined_glyphs']<1000:
                            raise AssertionError(f'Missing native feature: {report}')
                        layers=report['layers']
                        if not any(l['locked'] and not l['printable'] for l in layers) or not any(not l['visible'] for l in layers):
                            raise AssertionError('Missing layer attributes')
                    if name=='pages':
                        box=report['page_box'];size=(box[2]-box[0],box[3]-box[1])
                        if size!=((1150,1620) if i in (0,2) else (1620,1150)):
                            raise AssertionError(f'Wrong rotated/UserUnit artboard: {size}')
                    if name=='fallback':
                        reason=manifest[name][i]['reason_contains']
                        if reason.lower() not in report['fallback_reason'].lower():raise AssertionError(f'Unexpected fallback reason: {report}')
                        try:convert(source,output/f'strict-{i+1}.ai',page_number=i+1,raster_fallback=False)
                        except Exception as error:
                            from pdf2ai.vector import ConversionError
                            if not isinstance(error,ConversionError):raise
                        else:raise AssertionError('Strict mode should refuse fallback page')
                    with pikepdf.open(dest) as converted:
                        if not read_private(converted):raise AssertionError('Missing native editing data')
                        if converted.pages[0].obj.PieceInfo.Illustrator.Private.CreatorVersion!=24:raise AssertionError('Wrong AI version')
                    with pymupdf.open(dest) as converted:
                        matrix=pymupdf.Matrix(0.35,0.35) if name=='native' else pymupdf.Matrix(1,1)
                        if original[i].get_pixmap(matrix=matrix).samples!=converted[0].get_pixmap(matrix=matrix).samples:raise AssertionError(f'Preview changed: {name}/{i+1}')
                    report['input']=str(source.relative_to(ROOT))
                    report['output']=str(dest.relative_to(ROOT))
                    reports.append(report);print(f'PASS {name} page {i+1}: {report["conversion_mode"]}')
        (output/'verification.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if args.verify_ghostscript:
            # Reuse the existing page's label/font for the optional text-only
            # preprocessor check; the scratch PDF stays in project/output.
            with tempfile.TemporaryDirectory(prefix='gs-',dir=output) as directory:
                source=Path(directory)/'text.pdf'
                with pikepdf.open(sample/'conversion_pages.pdf') as pdf:
                    while len(pdf.pages)>1:del pdf.pages[-1]
                    page=pdf.pages[0];page.Contents=page.Contents[-1]
                    if '/Group' in page.obj:del page.obj['/Group']
                    pdf.save(source)
                report=convert(source,output/'ghostscript.ai',overwrite=True,outline_text=True,raster_fallback=False)
            if not report['text_outlined'] or report['rasterized']:raise AssertionError('Ghostscript outlining failed')
            report['input']='sample/conversion_pages.pdf (text label)'
            report['output']=str((output/'ghostscript.ai').relative_to(ROOT))
            (output/'ghostscript-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('PASS optional Ghostscript preprocessing')


if __name__=='__main__':main()
