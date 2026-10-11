"""Extract Lab entries from local Illustrator TOYO ACB books for data generation.

Run illustrator_toyo_reference.jsx afterwards to fill CMYK preview values.
ACB layout: https://www.adobe.com/devnet-apps/photoshop/fileformatashtml/
"""
import argparse
import json
from pathlib import Path
import struct


def read_book(path):
    data = Path(path).read_bytes()
    if data[:6] != b'8BCB\x00\x01':
        raise ValueError('Expected an ACB version 1 color book')
    position = 8

    def string():
        nonlocal position
        length = struct.unpack_from('>I', data, position)[0]
        position += 4
        value = data[position:position + length*2].decode('utf-16-be')
        position += length*2
        return value.split('=', 1)[-1] if value.startswith('$$$/') else value

    title, prefix, postfix, description = [string() for _ in range(4)]
    count, per_page, key_page, model = struct.unpack_from('>4H', data, position)
    position += 8
    if model != 7:
        raise ValueError('Expected a Lab color book')
    colors = {}
    for _ in range(count):
        name = string()
        position += 6  # Swatch key.
        lightness, a, b = data[position:position+3]
        position += 3
        if name:
            full_name = prefix + name + postfix
            if full_name in colors:
                raise ValueError('Duplicate swatch name')
            colors[full_name] = {'lab': [lightness*100/255, a-128, b-128]}
    return colors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('books', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    colors = {}
    for book in args.books:
        entries = read_book(book)
        if colors.keys() & entries.keys():
            raise ValueError('Overlapping color book names')
        colors.update(entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(colors, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'{len(colors)} Lab swatches: {args.output}')


if __name__ == '__main__':
    main()
