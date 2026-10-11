"""Small real-application regression cases for packed samples and Indexed Decode."""
import json
from pathlib import Path

import pikepdf
from pdf2ai.native import convert


def main():
    directory=Path(__file__).resolve().parents[1]/'output/fidelity-check/after'
    reports=[]
    for name,bits,raw,model,decode in [
        ('packed-rgb-1',1,b'\xa0\x40','DeviceRGB',None),
        ('packed-rgb-2',2,b'\x1c\xb0','DeviceRGB',None),
        ('packed-rgb-4',4,b'\x08\xf0\xf8\x00','DeviceRGB',None),
        ('packed-cmyk-2',2,b'\x05\xaf','DeviceCMYK',[1,0]*4),
        ('indexed-decode',2,b'\x1b','Indexed',[2,-1]),
    ]:
        pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,140))
        image=pdf.make_stream(raw)
        image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=4 if model=='Indexed' else 1,
                     Height=1 if model=='Indexed' else 2,BitsPerComponent=bits))
        image.ColorSpace=(pikepdf.Array([pikepdf.Name.Indexed,pikepdf.Name.DeviceRGB,2,
                          pikepdf.String(b'\xff\0\0\0\xff\0\0\0\xff')])
                          if model=='Indexed' else pikepdf.Name('/'+model))
        if decode is not None:image.Decode=decode
        if model=='Indexed':image.Mask=[1,1]
        page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image))
        page.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
        page.Contents=pdf.make_stream(b'0.6 0.6 0.6 rg 0 0 200 140 re f q 160 0 0 100 20 20 cm /Im Do Q')
        source=directory/(name+'.pdf');output=directory/(name+'.ai')
        pdf.save(source)
        reports.append(convert(source,output,overwrite=True,raster_fallback=False))
    (directory/'packed-image-conversion.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print('Generated',len(reports),'native cases')


if __name__=='__main__':main()
