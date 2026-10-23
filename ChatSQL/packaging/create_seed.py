"""Create a publishable seed without business data or model credentials."""

import argparse
import shutil
import tempfile
from pathlib import Path

from create_public_seed import export_public_seed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()
    source, target = args.source.resolve(), args.target.resolve()
    if source != target and (source in target.parents or target in source.parents):
        raise ValueError("Source and target must be separate directories.")
    expected_target = Path(__file__).resolve().parents[1] / "backend" / "app" / "seed" / "ChatSQLData"
    if target != expected_target:
        raise ValueError("Build seed target must be backend/app/seed/ChatSQLData.")
    with tempfile.TemporaryDirectory(prefix="chatsql-public-seed-") as temp:
        clean = Path(temp) / "ChatSQLData"
        export_public_seed(source, clean)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(clean, target)


if __name__ == "__main__":
    main()
