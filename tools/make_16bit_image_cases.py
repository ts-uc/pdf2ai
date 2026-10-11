"""Regression case for applying 16-bit Decode before quantization."""
import json
from pathlib import Path

import pikepdf
from pdf2ai.native import convert


def main():
    directory=Path(__file__).resolve().parents[1]/'output/fidelity-check/after'
    reports=[]
    for name,model,channels in [('image16-decode','DeviceGray',1)]:
        pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,140))
        values=(258,20000,65000)
        image=pdf.make_stream(b''.join(v.to_bytes(2,'big')*channels for v in values))
        image.update(pikepdf.Dictionary(Subtype=pikepdf.Name.Image,Width=3,Height=1,
                     BitsPerComponent=16,ColorSpace=pikepdf.Name('/'+model)))
        image.Decode=[0,.5]*channels
        page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image))
        page.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
        page.Contents=pdf.make_stream(b'0.6 0.6 0.6 rg 0 0 200 140 re f q 160 0 0 100 20 20 cm /Im Do Q')
        source=directory/(name+'.pdf');output=directory/(name+'.ai')
        pdf.save(source)
        reports.append(convert(source,output,overwrite=True,raster_fallback=False))
    (directory/'image16-conversion.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print('Generated',len(reports),'native cases')


if __name__=='__main__':main()
