"""Test configuration: isolate tests on a throwaway SQLite database.

Runs before any backend import so config picks up the test DATABASE_URL.
"""
import os
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="ava_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DIR}/test.db"
os.environ["DRY_RUN"] = "true"
os.environ["DOWNLOADS_DIR"] = os.path.join(_TMP_DIR, "downloads")
os.environ["PROCESSED_DIR"] = os.path.join(_TMP_DIR, "processed")
