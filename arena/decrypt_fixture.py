"""Decrypt the owner-provided official evaluation fixture on the cloud host."""
import io
import os
import zipfile
from pathlib import Path
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parents[1]
payload = Fernet(os.environ["ARENA_FIXTURE_KEY"].encode()).decrypt((root / "fixture.enc").read_bytes())
target = root / "runtime/official"; target.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    for item in archive.infolist():
        path = (target / item.filename).resolve()
        if not path.is_relative_to(target.resolve()): raise ValueError("Invalid fixture member")
    archive.extractall(target)
print("Official evaluation fixture decrypted; no policy loaded on host.")
