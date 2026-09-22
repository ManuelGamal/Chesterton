"""The coverage exporter's source, for uploading into a sandbox.

The exporter lives in its own file so it stays a real, importable-by-path
Python script; see export_coverage.py for why it streams.
"""

from pathlib import Path

EXPORTER_SOURCE = (Path(__file__).parent / "export_coverage.py").read_text(encoding="utf-8")
