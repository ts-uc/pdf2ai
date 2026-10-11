"""Small independent fixtures for Illustrator round-trip visual comparisons."""
import argparse
import json
from pathlib import Path
import sys

import pikepdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from pdf2ai.native import convert
from make_conversion_suite import document, gradient_scene, image_scene


def cases():
    for bits in (1,2,4,8):
        pdf=image_scene('indexed');image=pdf.pages[0].Resources.XObject.Im
        row=bytearray((8*bits+7)//8)
        for x in range(8):row[x*bits//8]|=(x%2)<<(8-bits-x*bits%8)
        image.write(bytes(row)*4);image.BitsPerComponent=bits;image.Mask=[1,1]
        yield f'image-indexed-key-{bits}bit',pdf
    for name,matrix in (('shear','1.5 0.2 0.5 0.7 20 20'),('reflection','-1.5 0.2 0.5 0.7 350 20')):
        for join in (0,1,2):
            for cap in (0,1,2):
                yield f'dash-frame-{name}-j{join}-c{cap}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 8 w {join} j {cap} J [37 19] 11 d 20 20 160 90 re S Q')
            yield f'dash-polyline-{name}-j{join}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 8 w {join} j 1 J [57 13] 4 d 20 20 m 100 110 l 180 20 l S Q')
        for phase in (0,7):
            yield f'dash-dotted-frame-{name}-{phase}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 8 w 1 J [0 15] {phase} d 20 20 160 90 re S Q')
            yield f'dash-seam-{name}-{phase}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 8 w 0 j 2 J [70 31] {phase} d 20 20 80 50 re S Q')
        yield f'dash-full-frame-{name}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 8 w 0 j 1 J [1000 10] 0 d 20 20 160 90 re S Q')
    yield 'dash-polyline-alpha',document('q 1.5 0.2 0.5 0.7 20 20 cm /A gs 0.2 0.4 0.8 RG 8 w 1 j 1 J [57 13] 4 d 20 20 m 100 110 l 180 20 l S Q',pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(CA=.4))))
    for name,matrix in (('shear','1.5 0.2 0.5 0.7 20 20'),('reflection','-1.5 0.2 0.5 0.7 350 20')):
        for join in (0,1,2):
            for cap in (0,1,2):
                yield f'polyline-{name}-j{join}-c{cap}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 12 w {join} j {cap} J 20 20 m 100 100 l 180 20 l S Q')
            yield f'polygon-{name}-j{join}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 12 w {join} j 20 20 m 100 110 l 180 20 l h S Q')
            yield f'frame-corner-{name}-j{join}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 12 w {join} j 20 20 160 90 re S Q')
        yield f'polyline-miter-limit-{name}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 12 w 1 M 20 20 m 100 110 l 115 20 l S Q')
        for phase in (0,7):
            yield f'dotted-{name}-{phase}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 8 w 1 J [0 15] {phase} d 20 20 m 180 110 l S Q')
    yield 'polyline-alpha',document('q 1.5 0.2 0.5 0.7 20 20 cm /A gs 0.2 0.4 0.8 RG 12 w 1 j 1 J 20 20 m 100 110 l 180 20 l S Q',pikepdf.Dictionary(ExtGState=pikepdf.Dictionary(A=pikepdf.Dictionary(CA=.4))))
    for name,matrix in (('shear','1.5 0.2 0.5 0.7 20 20'),('reflection','-1.5 0.2 0.5 0.7 350 20')):
        for cap in (0,1,2):
            yield f'stroke-{name}-cap{cap}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 16 w {cap} J 20 20 m 180 110 l S Q')
            yield f'dash-{name}-cap{cap}',document(f'q {matrix} cm 0.2 0.4 0.8 RG 8 w {cap} J [17 11] 9 d 20 20 m 180 110 l S Q')
    yield 'dash-odd-phase',document('q 1.5 0.2 0.5 0.7 20 20 cm 0.2 0.4 0.8 RG 8 w 1 J [13 7 5] 68 d 20 20 m 180 110 l S Q')
    yield 'dash-subpath-reset',document('q 1.5 0.2 0.5 0.7 20 20 cm 0.2 0.4 0.8 RG 8 w 2 J [17 11] 9 d 20 20 m 100 70 l 100 110 m 180 110 l S Q')
    for name,matrix in (('shear','1.5 0.2 0.5 0.7 20 20'),('reflection','-1.5 0.2 0.5 0.7 350 20')):
        for width in (8,100):
            yield f'frame-{name}-{width}',document(f'q {matrix} cm 0.2 0.4 0.8 RG {width} w 20 20 160 90 re S Q')
    yield 'frame-negative-size',document('q 1.5 0.2 0.5 0.7 20 20 cm 0.2 0.4 0.8 RG 8 w 180 110 -160 -90 re S Q')
    yield 'frame-fill-stroke',document('q 1.5 0.2 0.5 0.7 20 20 cm 0.8 0.2 0.2 rg 0.2 0.4 0.8 RG 8 w 20 20 160 90 re B Q')
    yield 'clip-hole', document('q 30 30 320 130 re 120 60 100 60 re W* n 0 0.5 0 rg 0 0 400 200 re f Q')
    yield 'clip-disjoint', document('q 30 30 100 100 re 220 30 100 100 re W n 1 0 0 rg 0 0 400 200 re f Q')
    yield 'text-clip', document('q BT /F 100 Tf 7 Tr 1 0 0 1 15 40 Tm (ABC) Tj ET 0 0.5 0.8 rg 0 0 400 200 re f Q',
        pikepdf.Dictionary(Font=pikepdf.Dictionary(F=pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica))))
    for model in ('RGB', 'Gray'):
        yield f'gradient-{model}-axial', gradient_scene(model)
        yield f'gradient-{model}-radial', gradient_scene(model, radial=True)
    yield 'gradient-rotated', gradient_scene('RGB', pattern=True)
    for name,coords in (('offset',(0,100,400,100)),('diagonal',(20,20,200,160)),('reflected',(350,100,30,100))):
        pdf=gradient_scene('RGB');pdf.pages[0].Resources.Shading.S.Coords=list(coords)
        yield 'gradient-'+name,pdf
    pdf=gradient_scene('RGB', pattern=True)
    pdf.pages[0].Resources.Pattern.P.Matrix=[2,0.5,0.7,1,20,-30]
    yield 'gradient-shear',pdf
    yield 'gradient-nonlinear',gradient_scene('RGB',exponent=2)
    pdf=gradient_scene('RGB',radial=True)
    form=pdf.pages[0].as_form_xobject()
    wrapped=document('q 0.7 0 0 0.7 50 30 cm /Form Do Q')
    wrapped.pages[0].Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Form=wrapped.copy_foreign(form)))
    yield 'gradient-radial-form',wrapped
    pdf=gradient_scene('RGB',radial=True)
    pdf.pages[0].Resources.Shading.S.Coords=[175,120,0,200,100,75]
    yield 'gradient-radial-focus',pdf
    for kind in ('rgb', 'soft-mask', 'hard-mask', 'color-key', 'cmyk-soft-mask'):
        yield 'image-' + kind, image_scene(kind)
    pdf=image_scene('soft-mask');pdf.pages[0].Resources.XObject.Im.SMask.Decode=[1,0]
    yield 'image-inverted-soft-mask',pdf
    for matte in ((1,1,1),(0,0,0)):
        pdf=image_scene('soft-mask');image=pdf.pages[0].Resources.XObject.Im
        alpha=image.SMask.read_bytes();original=image.read_bytes()
        image.write(bytes(round(v*alpha[i//3]/255+255*matte[i%3]*(1-alpha[i//3]/255)) for i,v in enumerate(original)))
        image.SMask.Matte=list(matte)
        yield 'image-matte-'+('white' if matte[0] else 'black'),pdf
    for bits in (1,2,4,16):
        pdf=image_scene('soft-mask');mask=pdf.pages[0].Resources.XObject.Im.SMask
        if bits==16:
            data=b''.join((x*65535//7).to_bytes(2,'big') for y in range(4) for x in range(8))
        else:
            row=bytearray(8*bits//8)
            for x in range(8):row[x*bits//8]|=(x*((1<<bits)-1)//7) << (8-bits-x*bits%8)
            data=bytes(row)*4
        mask.write(data);mask.BitsPerComponent=bits
        yield f'image-soft-mask-{bits}bit',pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='after', choices=('before','after'))
    args = parser.parse_args()
    base = ROOT / 'output' / 'fidelity-check'
    folder = base / args.run
    if args.run == 'before' and (folder / 'conversion.json').exists():
        raise FileExistsError('The saved baseline is preserved; use --run after for the current converter.')
    folder.mkdir(parents=True, exist_ok=True)
    reports = []
    for name, pdf in cases():
        # Explicit RGB blending space removes unrelated working-CMYK differences.
        pdf.pages[0].obj.Group = pikepdf.Dictionary(S=pikepdf.Name.Transparency,CS=pikepdf.Name.DeviceRGB)
        for key, font in list(pdf.pages[0].Resources.get('/Font', {}).items()):
            if not font.is_indirect:
                pdf.pages[0].Resources.Font[key] = pdf.make_indirect(font)
        source = folder / (name + '.pdf')
        pdf.save(source)
        pdf.close()
        report = convert(source, folder / (name + '.ai'), overwrite=True, raster_fallback=False)
        reports.append(report)
    (folder / 'conversion.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    (base / 'run.json').write_text(json.dumps({'run':args.run}))
    print(folder)


if __name__ == '__main__':
    main()
