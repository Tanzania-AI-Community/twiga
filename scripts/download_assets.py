"""Download the pinned assets used by Twiga's local seed setup."""

import hashlib
import json
import sys
from http.client import HTTPException
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts/assets/downloads.json"


def download(path: Path, url: str, expected_sha256: str) -> None:
    if path.exists():
        with path.open("rb") as existing:
            if hashlib.file_digest(existing, "sha256").hexdigest() == expected_sha256:
                return

    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        pending = Path(temporary.name)
        try:
            digest = hashlib.sha256()
            with urlopen(url, timeout=30) as response:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    temporary.write(chunk)
            if digest.hexdigest() != expected_sha256:
                raise ValueError("SHA-256 mismatch")
            temporary.close()
            pending.chmod(0o644)
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


def main() -> int:
    for asset in json.loads(MANIFEST.read_text(encoding="utf-8")):
        destination = Path(asset["directory"]) / asset["filename"]
        try:
            download(ROOT / destination, asset["url"], asset["sha256"])
        except (HTTPException, OSError, ValueError) as error:
            print(f"Could not prepare {destination}: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
