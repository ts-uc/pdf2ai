#!/usr/bin/env python3
"""ソースから起動するためのランチャー。projectディレクトリでpip install .を使用。"""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
if '--gui' in sys.argv:
    from pdf2ai.gui import main
    main()
else:
    from pdf2ai.cli import main
    raise SystemExit(main())
