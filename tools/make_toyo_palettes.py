"""Generate separate Scribus TOYO palettes from the bundled TOYO Lab data."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def main():
    root = Path(__file__).resolve().parents[1]
    data = root/'src/pdf2ai/data/toyo_lab.json'
    colors = json.loads(data.read_text(encoding='utf-8'))
    # Normalize ExtendScript's platform newlines without modifying any DIC file.
    data.write_text('{\n'+',\n'.join(
        '  '+json.dumps(name, ensure_ascii=False)+': '+json.dumps(value, separators=(',', ':'))
        for name, value in colors.items())+'\n}\n', encoding='utf-8')
    for prefix, filename, title in (
        ('CF ', 'TOYO_COLOR_FINDER_Lab.xml', 'TOYO COLOR FINDER Spot Colors (Lab)'),
        ('TOYO ', 'TOYO_94_Lab.xml', 'TOYO 94 COLOR FINDER Spot Colors (Lab)'),
    ):
        palette = ET.Element('SCRIBUSCOLORS', Name=title)
        palette.append(ET.Comment(' Generated from src/pdf2ai/data/toyo_lab.json; Lab spot colors. '))
        for name, color in colors.items():
            if name.startswith(prefix):
                lightness, a, b = color['lab']
                ET.SubElement(palette, 'COLOR', NAME=name, SPACE='Lab', L=str(lightness),
                              A=str(a), B=str(b), Spot='1', Register='0')
        ET.indent(palette)
        path = root/'integrations/scribus/palettes'/filename
        ET.ElementTree(palette).write(path, encoding='utf-8', xml_declaration=True)
        print(f'{len(palette)-1} colors: {path.name}')


if __name__ == '__main__':
    main()
