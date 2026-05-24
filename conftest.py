"""Ensure the project root is importable as the `app` package during tests."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Tests must never touch real external APIs.
os.environ.setdefault("USE_MOCKS", "1")
