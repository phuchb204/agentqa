import json
import shutil
import sys
from pathlib import Path


def generate_variant(base_dir: Path, out_dir: Path, spec: dict) -> Path:
    target = Path(out_dir) / spec["name"]
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(base_dir, target)
    for change in spec.get("changes", []):
        file_path = target / change["file"]
        original = file_path.read_text(encoding="utf-8")
        if change["before"] not in original:
            raise ValueError(f"pattern not found in {change['file']}: {change['before']!r}")
        file_path.write_text(original.replace(change["before"], change["after"]), encoding="utf-8")
    return target


def main() -> None:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    site_dir = Path(__file__).resolve().parents[1]
    result = generate_variant(site_dir / "base", site_dir / "variants", spec)
    print(result)


if __name__ == "__main__":
    main()
