"""DIC名が一致する特色に、カラーブックのLab定義を設定する。"""
from functools import lru_cache
from importlib.resources import files
import json


@lru_cache(maxsize=1)
def _colors():
    return json.loads(files('pdf2ai').joinpath('data/dic_lab.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _aliases():
    candidates = {}
    for name in _colors():
        base = name.rstrip('*').removesuffix('s')
        candidates.setdefault(base, []).append(name)
    # Use only unambiguous entries; exact book names always take precedence.
    return {base: names[0] for base,names in candidates.items() if len(names)==1}


def dic_name(name):
    """末尾のs・*を省略したDIC名を、登録済みの正式名に解決する。"""
    if name in _colors():
        return name
    return _aliases().get(name.rstrip('*').removesuffix('s'))


def dic_color(name):
    return _colors().get(dic_name(name))
