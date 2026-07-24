from pathlib import Path


def test_memory_workspace_has_real_nodes_isolation_and_holographic_name_toggle():
    source = Path("ui_mk2/memory_workspace.py").read_text(encoding="utf-8")
    assert "REAL MEMORY TOPOLOGY" in source
    assert 'id="labelsToggle"' in source
    assert "showNames=e.target.checked" in source
    assert "selected=selected===n.id?null:n.id" in source
    assert "CLICK NUCLEUS TO ISOLATE" in source
    assert "FILTER REAL MEMORIES" in source
    assert "Obsidian" not in source
