"""TOYO専用データ、特色名、濃度、ScribusパレットとDICとの独立性。"""
from pathlib import Path
import xml.etree.ElementTree as ET

import pikepdf
import pytest

from pdf2ai.toyo import _colors, toyo_color, toyo_name
from pdf2ai.dic import dic_color, dic_name
from pdf2ai.cli import main
from pdf2ai.multiboard import convert_document
from pdf2ai.native import convert, read_private
from pdf2ai.vector import ConversionError, read_spot


def separation(name, full, *, lab=False):
    alternate = pikepdf.Name.DeviceCMYK
    if lab:
        alternate = pikepdf.Array([pikepdf.Name.Lab, pikepdf.Dictionary(
            WhitePoint=[.964203, 1, .824905], Range=[-128, 127, -128, 127])])
    function = pikepdf.Dictionary(FunctionType=2, Domain=[0, 1],
                                  C0=[100, 0, 0] if lab else [0]*4, C1=full, N=1)
    return pikepdf.Array([pikepdf.Name.Separation, pikepdf.Name('/'+name), alternate, function])


@pytest.mark.parametrize('name,canonical', [
    ('CF 10001', 'CF 10001*'), ('CF10001', 'CF 10001*'),
    ('TOYO CF 10001', 'CF 10001*'), ('TOYO CF10001', 'CF 10001*'),
    ('TOYO 10001', 'CF 10001*'), ('TOYO 0001', 'TOYO 0001'),
    ('TOYO 1', 'TOYO 0001'), ('TOYO 1050', 'TOYO 1050*'),
])
def test_number_aliases(name, canonical):
    assert toyo_name(name) == canonical
    assert toyo_color(name) == toyo_color(canonical)


def test_all_book_colors_have_valid_values_and_resolve():
    colors = _colors()
    assert len(colors) == 2129
    assert sum(name.startswith('CF ') for name in colors) == 1079
    assert sum(name.startswith('TOYO ') for name in colors) == 1050
    for name, value in colors.items():
        assert toyo_name(name) == name
        assert toyo_name(name.rstrip('*')) == name
        assert len(value['cmyk']) == 4 and all(0 <= v <= 1 for v in value['cmyk'])
        assert 0 <= value['lab'][0] <= 100
        assert all(-128 <= v <= 127 for v in value['lab'][1:])
    assert colors['CF 10001*']['lab'] == pytest.approx([109*100/255, 56, -17])
    assert colors['TOYO 0001']['lab'] == pytest.approx([109*100/255, 56, -19])


def test_dic_and_toyo_names_remain_independent():
    assert toyo_name('DIC 1') is None and toyo_color('DIC 1s') is None
    assert dic_name('TOYO 1') is None and dic_color('CF 10001*') is None
    assert dic_color('DIC 1')['cmyk'] == [0, .16, .17, 0]


@pytest.mark.parametrize('name', ['TOYO test', 'TOYO 999999', 'TOYO 1 custom',
                                   'My TOYO 0001', 'CF 99999', '10001'])
def test_unregistered_names_preserve_original_cmyk(name):
    assert toyo_name(name) is None
    spot = read_spot(separation(name, [.2, .3, .4, 0]))
    assert spot.name == name and spot.lab is None and spot.cmyk == (.2, .3, .4, 0)


@pytest.mark.parametrize('lab', [False, True])
def test_registered_toyo_spots_support_cmyk_and_actual_lab(lab):
    full = [44, 55, -16] if lab else [.2, .3, .4, 0]
    spot = read_spot(separation('CF 10001', full, lab=lab))
    assert spot.name == 'CF 10001*'
    assert spot.lab == tuple(full if lab else toyo_color('CF 10001')['lab'])


def test_toyo_lookup_does_not_hide_invalid_tint_or_white_point():
    space = separation('TOYO 0001', [.2, .3, .4, 0])
    space[3].N = 2
    with pytest.raises(ConversionError, match='Nonlinear'):
        read_spot(space)
    space = separation('CF 10001', [44, 55, -16], lab=True)
    space[2][1].WhitePoint = [1, 1, 1]
    with pytest.raises(ConversionError, match='D50'):
        read_spot(space)


def test_toyo_tints_alias_deduplication_and_dic_in_one_document(tmp_path):
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(200, 100))
    page.Resources = pikepdf.Dictionary(ColorSpace=pikepdf.Dictionary(
        A=separation('CF10001', [.2, .3, .4, 0]),
        B=separation('CF 10001*', [.2, .3, .4, 0]),
        C=separation('TOYO 1', [.2, .3, .4, 0]),
        D=separation('DIC 1', [.2, .3, .4, 0])))
    page.Contents = pdf.make_stream(
        b'/A cs 0.25 scn 10 10 30 30 re f /B CS 0.5 SCN 2 w 50 10 30 30 re S '
        b'/C cs 1 scn 90 10 30 30 re f /D cs 1 scn 130 10 30 30 re f')
    source = tmp_path/'source.pdf'; output = tmp_path/'out.ai'; pdf.save(source)
    report = convert(source, output, raster_fallback=False)
    assert not report['rasterized']
    assert [s['name'] for s in report['spots']] == ['CF 10001*', 'TOYO 0001', 'DIC 1s']
    assert [s['alternate_space'] for s in report['spots']] == ['Lab', 'Lab', 'CMYK']
    with pikepdf.open(output) as ai:
        private = read_private(ai)
        assert private.count(b'(CF 10001*)\rPc') == 1
        assert b'(CF 10001*) 0.75 2 Xx' in private
        assert b'(CF 10001*) 0.5 2 XX' in private
    assert main([str(source), '--check']) == 0
    combined = convert_document(source, tmp_path/'combined.ai', raster_fallback=False)
    assert combined[0]['spots'] == report['spots']


@pytest.mark.parametrize('filename,prefix,count', [
    ('TOYO_COLOR_FINDER_Lab.xml', 'CF ', 1079), ('TOYO_94_Lab.xml', 'TOYO ', 1050),
])
def test_separate_toyo_scribus_palettes(filename, prefix, count):
    root = Path(__file__).resolve().parents[1]
    palette = ET.parse(root/'integrations/scribus/palettes'/filename).getroot()
    entries = palette.findall('COLOR')
    assert len(entries) == count
    assert len({entry.attrib['NAME'] for entry in entries}) == count
    for entry in entries:
        attributes = entry.attrib
        assert attributes['NAME'].startswith(prefix)
        assert attributes['SPACE'] == 'Lab' and attributes['Spot'] == '1'
        assert [float(attributes[key]) for key in ('L', 'A', 'B')] == _colors()[attributes['NAME']]['lab']
    dic_entries = ET.parse(root/'integrations/scribus/palettes/DIC_Lab.xml').getroot().findall('COLOR')
    assert len(dic_entries) == 1280 and all(entry.attrib['NAME'].startswith('DIC ') for entry in dic_entries)
