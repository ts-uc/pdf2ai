"""Keep automatically generated test artifacts inside this project."""
from pathlib import Path


def pytest_configure(config):
    if config.option.basetemp is None:
        config.option.basetemp = str(Path(__file__).resolve().parent / '.tmp')
