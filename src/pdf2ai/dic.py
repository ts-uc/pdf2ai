"""DIC名が一致する特色に、カラーブックのLab定義を設定する。"""
from functools import lru_cache
from importlib.resources import files
import json


@lru_cache(maxsize=1)
def _colors():
    return json.loads(files('pdf2ai').joinpath('data/dic_lab.json').read_text(encoding='utf-8'))


def dic_color(name):
    # Suffixes such as s and * distinguish actual book entries. Do not guess
    # a color from its number or overwrite a similarly named custom spot.
    return _colors().get(name)
