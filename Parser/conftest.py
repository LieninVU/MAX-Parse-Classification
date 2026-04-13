"""
conftest.py — глобальные fixtures и mock для тестов Parser.
"""

import sys
from unittest.mock import MagicMock

# Мокаем pymax ДО импорта comment_parser
pymax_mock = MagicMock()
pymax_mock.MaxClient = MagicMock()
sys.modules.setdefault("pymax", pymax_mock)
