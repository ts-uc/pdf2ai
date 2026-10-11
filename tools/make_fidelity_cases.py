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
