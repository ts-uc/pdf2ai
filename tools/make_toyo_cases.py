"""Generate TOYO Lab spot cases for Illustrator save/reopen and PDF comparison."""
import json
from pathlib import Path

import pikepdf

from pdf2ai.native import convert
from pdf2ai.toyo import toyo_color


def main():
    folder = Path(__file__).resolve().parents[1]/'output/fidelity-check/after'
    folder.mkdir(parents=True, exist_ok=True)
    cases = [
        ('toyo-current', ['CF 10001', 'CF 10500', 'CF 11050']),
        ('toyo-94', ['TOYO 1', 'TOYO 500', 'TOYO 1050']),
        ('toyo-basic', ['CF 59 Rose', 'CF 78 Green', 'CF Millennium Black']),
        ('toyo-aliases', ['CF10001', 'CF 10001*', 'TOYO 0001']),
    ]
    reports = []
    for stem, names in cases:
        pdf = pikepdf.new()
        page = pdf.add_blank_page(page_size=(240, 150))
        spaces = pikepdf.Dictionary()
        commands = []
        for index, name in enumerate(names):
            color = toyo_color(name)
            if color is None:
                raise ValueError('Unknown reference color: '+name)
            alternate = pikepdf.Array([pikepdf.Name.Lab, pikepdf.Dictionary(
                WhitePoint=[.964203, 1, .824905], Range=[-128, 127, -128, 127])])
            function = pikepdf.Dictionary(FunctionType=2, Domain=[0, 1],
                                          C0=[100, 0, 0], C1=color['lab'], N=1)
            spaces[f'/S{index}'] = pikepdf.Array([
                pikepdf.Name.Separation, pikepdf.Name('/'+name), alternate, function])
            x = 10 + index*75
            commands.append(f'/S{index} cs 1 scn {x} 95 60 40 re f '
                            f'.5 scn {x} 50 60 35 re f '
                            f'/S{index} CS .25 SCN 3 w {x} 10 60 30 re S')
        page.Resources = pikepdf.Dictionary(ColorSpace=spaces)
        page.Contents = pdf.make_stream(' '.join(commands).encode('ascii'))
        source = folder/(stem+'.pdf'); output = folder/(stem+'.ai')
        pdf.save(source)
        reports.append(convert(source, output, overwrite=True, raster_fallback=False))
    (folder/'toyo-conversion.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('Generated '+', '.join(stem for stem, _ in cases))


if __name__ == '__main__':
    main()
