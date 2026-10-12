"""Generate independent Illustrator fixtures for the medium-difficulty extensions."""
from pathlib import Path
import pikepdf
import pymupdf


def generate(folder):
    folder = Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    for form in (False,True):
        pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(120,100))
        content=b'q 80 0 0 60 20 20 cm BI /W 2 /H 1 /BPC 8 /CS /RGB ID \xff\0\0\0\0\xff EI Q'
        if form:
            obj=pdf.make_stream(content);obj.Subtype=pikepdf.Name.Form;obj.BBox=[0,0,120,100];obj.Resources=pikepdf.Dictionary()
            page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(F=obj));page.Contents=pdf.make_stream(b'/F Do')
        else:page.Contents=pdf.make_stream(content)
        pdf.save(folder/('medium-inline-form.pdf' if form else 'medium-inline.pdf'))
    for model,raw in (('RGB',bytes([255,0,0,0,255,0,0,0,255,255,255,0])),
                      ('CMYK',bytes([0,255,255,0,255,0,255,0,255,255,0,0,0,0,255,0]))):
        pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(120,100));image=pdf.make_stream(raw)
        image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=2,Height=2,BitsPerComponent=8,ColorSpace=pikepdf.Name('/Alias')))
        page.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(Alias=pikepdf.Name('/Device'+model)),XObject=pikepdf.Dictionary(I=image))
        page.Contents=pdf.make_stream(b'80 0 0 60 20 20 cm /I Do');pdf.save(folder/f'medium-alias-{model}.pdf')
    for indexed in (False,True):
        pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(120,100));image=pdf.make_stream(bytes([128,128,200,200]*4) if indexed else bytes([128,0,0,128,0,0,0,200,0,0,200,0]*4))
        palette=bytes(v for i in range(256) for v in (i,0,0))
        image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=4,Height=4,BitsPerComponent=8,
            ColorSpace=pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name.DeviceRGB,255,pikepdf.String(palette)]) if indexed else pikepdf.Name.DeviceRGB))
        mask=pdf.make_stream(bytes([128,255,255,128]));mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,
            Width=2,Height=2,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray))
        if indexed:
            mask=pdf.make_stream(bytes([128,128,255,255,128,128,255,255,255,255,128,128,255,255,128,128]))
            mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=4,Height=4,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray,Matte=[0]))
        image.SMask=mask;page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(I=image))
        page.Contents=pdf.make_stream(b'.3 .6 .8 rg 0 0 120 100 re f q 80 0 0 60 20 20 cm /I Do Q')
        pdf.save(folder/('medium-indexed-matte.pdf' if indexed else 'medium-aligned-mask.pdf'))
    for stem,width,height,mw,mh in (('coprime',3,2,2,3),('larger',2,2,4,4)):
        pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(120,100))
        image=pdf.make_stream(bytes(v for i in range(width*height) for v in ((i*43)%256,(i*97)%256,(i*151)%256)))
        image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=width,Height=height,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceRGB))
        mask=pdf.make_stream(bytes((i*53)%256 for i in range(mw*mh)))
        mask.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=mw,Height=mh,BitsPerComponent=8,ColorSpace=pikepdf.Name.DeviceGray))
        image.SMask=mask;page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(I=image))
        page.Contents=pdf.make_stream(b'.3 .6 .8 rg 0 0 120 100 re f q 80 0 0 60 20 20 cm /I Do Q')
        pdf.save(folder/f'medium-mask-{stem}.pdf')
    for model in ('RGB','CMYK'):
        for isolated,knockout in ((True,False),(False,True),(True,True)):
            pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(120,100))
            page.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name('/Device'+model),I=isolated,K=knockout)
            page.Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(ca=.5),M=pikepdf.Dictionary(BM=pikepdf.Name.Multiply)))
            red='1 0 0 rg' if model=='RGB' else '0 1 1 0 k'
            blue='0 0 1 rg' if model=='RGB' else '1 1 0 0 k'
            page.Contents=pdf.make_stream(f'/A gs {red} 10 10 70 60 re f /M gs {blue} 40 30 70 60 re f'.encode())
            pdf.save(folder/f'medium-page-group-{model}-{int(isolated)}-{int(knockout)}.pdf')
    strokes=[('butt-dots','0 J [0 8] 0 d 10 20 m 40 20 l S'),
             ('square-dots','2 J [0 8] 0 d 10 20 m 40 20 l S'),
             ('round-point','1 J 10 20 m 10 20 l S'),
             ('round-curve-point','1 J 10 20 m 10 20 10 20 10 20 c S'),
             ('move-only','1 J 10 20 m S'),
             *[(f'reversal-{join}',f'{join} j 10 20 m 40 20 l 10 20 l S') for join in range(3)]]
    for name,content in strokes:
        pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(100,60))
        page.Contents=pdf.make_stream(('2 0 0 1 0 0 cm .2 .4 .8 RG 8 w '+content).encode())
        pdf.save(folder/f'medium-stroke-{name}.pdf')
    for name,stem in (('CF 10001','current'),('TOYO 1','94'),('CF 59 Rose','basic')):
        pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(120,100))
        page.Resources=pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(S=pikepdf.Array([
            pikepdf.Name.Separation,pikepdf.Name('/'+name),pikepdf.Name.DeviceCMYK,
            pikepdf.Dictionary(FunctionType=2,Domain=[0,1],C0=[0]*4,C1=[1,0,0,0],N=1)])))
        page.Contents=pdf.make_stream(b'/S cs 1 scn 10 10 30 80 re f .5 scn 50 10 30 80 re f .25 scn 90 10 20 80 re f')
        pdf.save(folder/f'medium-toyo-cmyk-{stem}.pdf')
    with pymupdf.open() as document:
        page=document.new_page(width=120,height=100)
        page.draw_rect(pymupdf.Rect(10,10,80,70),color=None,fill=(1,0,0))
        annotation=page.add_rect_annot(pymupdf.Rect(40,30,110,90));annotation.set_colors(stroke=(0,0,1));annotation.update()
        document.bake(annots=True,widgets=True)
        document.save(folder/'medium-annotation-baked.pdf')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path)
    generate(parser.parse_args().folder)
