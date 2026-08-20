"""Shared environment established before any application module is imported."""
import atexit
import os
import shutil
import tempfile

TEST_DIRECTORY = tempfile.mkdtemp(prefix="automaton-tests-")
TEST_DB_PATH = os.path.join(TEST_DIRECTORY, "test.db")

os.environ.setdefault("AUTOMATON_MODE", "simulation")
os.environ.setdefault("CYCLE_SECONDS", "3600")
os.environ.setdefault("MIN_REPLICATION_AGE_HOURS", "0")
os.environ.setdefault("DATABASE_PATH", TEST_DB_PATH)


def cleanup() -> None:
    shutil.rmtree(TEST_DIRECTORY, ignore_errors=True)


atexit.register(cleanup)
