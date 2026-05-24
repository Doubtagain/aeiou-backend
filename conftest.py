"""Ensure the project root is importable as the `app` package during tests."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Tests must never touch real external APIs.
os.environ.setdefault("USE_MOCKS", "1")

# Tests use a throwaway SQLite file, not the project's voiceup.db.
os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + os.path.join(tempfile.gettempdir(), "voiceup_test.db")
)
