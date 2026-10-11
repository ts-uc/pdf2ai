"""Independent PDF fixtures for ICC conversion and native transparency groups."""
import argparse
import json
from pathlib import Path
import sys

import pikepdf
from PIL import ImageCms

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from pdf2ai.native import convert
from make_conversion_suite import document, image_scene


def group_scene(isolated, blend='Normal', opacity=.6, nested=False):
    pdf = document('0.8 0.2 0.1 rg 0 0 400 200 re f q /Outer gs /Form Do Q')
    page = pdf.pages[0]
    form = pdf.make_stream(b'0.1 0.3 0.9 rg 30 30 150 120 re f /Inner gs 0.1 0.8 0.3 rg 110 50 150 120 re f')
    form.Type=pikepdf.Name.XObject;form.Subtype=pikepdf.Name.Form;form.BBox=[0,0,400,200]
    form.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,I=isolated,K=False,CS=pikepdf.Name.DeviceRGB)
    form.Resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(Inner=pikepdf.Dictionary(ca=.5)))
    if nested:
        wrapper=pdf.make_stream(b'/Form Do')
        wrapper.Type=pikepdf.Name.XObject;wrapper.Subtype=pikepdf.Name.Form;wrapper.BBox=[0,0,400,200]
        wrapper.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,I=True,K=False,CS=pikepdf.Name.DeviceRGB)
        wrapper.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Form=form))
        form=wrapper
    page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Form=form),
                                     ExtGState=pikepdf.Dictionary(Outer=pikepdf.Dictionary(ca=opacity,BM=pikepdf.Name('/'+blend))))
    page.Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
    return pdf


def icc_scene(profile, components, image=False):
    if image:
        pdf=image_scene('cmyk-soft-mask' if components==4 else 'soft-mask')
    else:
        pdf=document('/Profile cs '+('0.6 0.1 0.2 0.1' if components==4 else '0.2 0.5 0.8')+' scn 30 30 300 130 re f')
    stream=pdf.make_stream(profile);stream.N=components
    space=pikepdf.Array([pikepdf.Name.ICCBased,stream])
    if image:pdf.pages[0].Resources.XObject.Im.ColorSpace=space
    else:pdf.pages[0].Resources.ColorSpace=pikepdf.Dictionary(Profile=space)
    pdf.pages[0].Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
    return pdf


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rgb-profile',type=Path)
    parser.add_argument('--cmyk-profile',type=Path)
    args=parser.parse_args()
    folder=ROOT/'output/fidelity-check/after'
    folder.mkdir(parents=True,exist_ok=True)
    fixtures=[]
    for isolated in (False,True):
        for blend in ('Normal','Multiply','Screen'):
            fixtures.append((f'group-i{int(isolated)}-{blend.lower()}',group_scene(isolated,blend)))
    fixtures.append(('group-nested',group_scene(True,nested=True)))
    for isolated in (False,True):
        pdf=group_scene(isolated)
        pdf.pages[0].Resources.XObject.Form.Group.K=True
        fixtures.append((f'group-knockout-i{int(isolated)}',pdf))
    for matrix_name,matrix in [('uniform',''),('shear','1.5 0.2 0.5 0.7 20 20 cm')]:
        for blend in ('Normal','Multiply'):
            for text in (False,True):
                resources=pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(ca=.8,CA=.4,BM=pikepdf.Name('/'+blend))))
                if text:
                    resources.Font=pikepdf.Dictionary(F=pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica))
                command='BT /F 55 Tf 2 Tr 1 0 0 1 20 50 Tm (BC) Tj ET' if text else '20 20 160 90 re B'
                pdf=document('0.8 0.8 0.8 rg 0 0 400 200 re f q '+matrix+' /A gs 0.8 0.2 0.2 rg 0.2 0.4 0.8 RG 8 w '+command+' Q',resources)
                pdf.pages[0].Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
                fixtures.append((f'group-combined-{matrix_name}-{blend.lower()}-'+('text' if text else 'path'),pdf))
    rgb=args.rgb_profile.read_bytes() if args.rgb_profile else ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    fixtures.extend([('icc-rgb-fill',icc_scene(rgb,3)),('icc-rgb-image',icc_scene(rgb,3,True))])
    if args.cmyk_profile:
        cmyk=args.cmyk_profile.read_bytes()
        fixtures.extend([('icc-cmyk-fill',icc_scene(cmyk,4)),('icc-cmyk-image',icc_scene(cmyk,4,True))])
    pdf=image_scene('cmyk-soft-mask')
    pdf.pages[0].Group=pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
    fixtures.append(('image-cmyk-normalized',pdf))
    reports=[]
    for name,pdf in fixtures:
        source=folder/(name+'.pdf');pdf.save(source);pdf.close()
        reports.append(convert(source,folder/(name+'.ai'),overwrite=True,raster_fallback=False))
    (folder/'color-transparency-conversion.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    (folder.parent/'run.json').write_text(json.dumps({'run':'after','cases':[name+'.ai' for name,_ in fixtures]}))
    print(len(fixtures),'cases')


if __name__=='__main__':main()
