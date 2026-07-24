from pathlib import Path


def test_open_map_keeps_dark_theme_with_readable_labels_and_boundaries():
    source = Path("ui_mk2/web_workspaces.py").read_text(encoding="utf-8")
    assert "'#f0fbff'" in source
    assert "'text-halo-width',1.15" in source
    assert "boundary|admin|border|country|state|province" in source
    assert "'line-color','#a9cbd4'" in source
    assert "'line-opacity',.46" in source
    assert "brightness(.92)" in source


def test_visible_brand_is_mark_li_everywhere():
    ui = Path("ui.py").read_text(encoding="utf-8")
    assert "MARK LI" in ui
    assert "MARK L\"" not in ui
    assert "MARK L  " not in ui
