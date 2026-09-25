from pathlib import Path

import pytest
from gen_variants import generate_variant


def _make_base(tmp_path: Path) -> Path:
    base = tmp_path / "base"
    base.mkdir()
    (base / "index.html").write_text(
        '<input id="new-todo"><button id="add-btn">Thêm</button>', encoding="utf-8"
    )
    (base / "app.js").write_text('document.getElementById("add-btn");', encoding="utf-8")
    return base


def test_generate_variant_replaces_patterns_in_all_files(tmp_path: Path):
    base = _make_base(tmp_path)
    spec = {
        "name": "id-change",
        "changes": [
            {"file": "index.html", "before": 'id="new-todo"', "after": 'id="task-input"'},
            {"file": "index.html", "before": 'id="add-btn"', "after": 'id="create-task"'},
            {"file": "app.js", "before": '"add-btn"', "after": '"create-task"'},
        ],
    }
    out = generate_variant(base, tmp_path / "variants", spec)
    html = (out / "index.html").read_text(encoding="utf-8")
    js = (out / "app.js").read_text(encoding="utf-8")
    assert 'id="task-input"' in html
    assert 'id="create-task"' in html
    assert '"create-task"' in js
    assert 'id="add-btn"' not in html
    assert 'id="new-todo"' in (base / "index.html").read_text(encoding="utf-8")


def test_generate_variant_raises_on_missing_pattern(tmp_path: Path):
    base = _make_base(tmp_path)
    spec = {
        "name": "bad",
        "changes": [{"file": "index.html", "before": "không-tồn-tại", "after": "x"}],
    }
    with pytest.raises(ValueError):
        generate_variant(base, tmp_path / "variants", spec)
