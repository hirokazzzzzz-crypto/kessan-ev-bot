"""売買前チェックシステム CLI の簡易エントリポイント。

例: python main.py entry / python main.py list / python main.py report --month 2026-08
"""
import sys

from pretrade.cli import main

if __name__ == "__main__":
    sys.exit(main())
