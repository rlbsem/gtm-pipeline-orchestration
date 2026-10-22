"""Optional pinned public audit assets. Not application dependencies or source API calls."""
import argparse
import hashlib
from pathlib import Path

import httpx

ASSETS = {
    "axe.min.js": ("https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.3/axe.min.js",
                   "880970c081707360e64f34cea25ff91892f5bc95675b0776925b9709dd8a68bb"),
    "mermaid.min.js": ("https://cdn.jsdelivr.net/npm/mermaid@11.12.0/dist/mermaid.min.js",
                       "07e37dfa97b337ccc85365d57eddf99b9706f09db3b59b260d0333b23b343c4b"),
}


def verified(folder):
    for name, (_, expected) in ASSETS.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected, "audit_asset_digest_mismatch"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("work/audit-tools"))
    folder = parser.parse_args().output
    folder.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in ASSETS.items():
        response = httpx.get(url, timeout=30, follow_redirects=False)
        response.raise_for_status()
        assert hashlib.sha256(response.content).hexdigest() == expected, "audit_download_digest_mismatch"
        (folder / name).write_bytes(response.content)
    verified(folder)
    print("Pinned axe-core 4.10.3 and Mermaid 11.12.0 verified; application unchanged.")
