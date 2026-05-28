"""Wrapper для PyInstaller - точка входа вне пакета src."""
import sys
import os

# Корень репо должен быть в sys.path
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

from src.main import main

if __name__ == "__main__":
    main()
