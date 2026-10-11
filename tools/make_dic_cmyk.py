"""Generate DIC-only CMYK conversion data from Illustrator's legacy DIC ACBL."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('book', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    book = ET.parse(args.book).getroot()
    prefix = book.find('./PrefixPostfixPairs/PrefixPostfixPair').attrib['Prefix']
    if prefix != 'DIC ':
        raise ValueError('Expected the DIC CMYK book')
    colors = {}
    for swatch in book.findall('./Swatches/Sp'):
        values = [float(value) for value in swatch.findtext('C').split()]
        if len(values) != 4 or not all(0 <= value <= 1 for value in values):
            raise ValueError('Invalid CMYK swatch')
        colors[prefix+swatch.attrib['N']] = {'cmyk': values}
    if len(colors) != 1280:
        raise ValueError('Expected 1280 DIC colors')
    (root/'src/pdf2ai/data/dic_cmyk.json').write_text(
        '{\n'+',\n'.join('  '+json.dumps(name)+': '+json.dumps(color, separators=(',', ':'))
                         for name, color in colors.items())+'\n}\n', encoding='utf-8')
    print(f'{len(colors)} DIC CMYK colors generated')


if __name__ == '__main__':
    main()
