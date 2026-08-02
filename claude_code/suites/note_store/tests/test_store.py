"""记忆库的基线测试。"""
from store import Store


def test_existing_items_loaded():
    s = Store()
    assert len(s.all()) >= 2
    assert any("systemd" in it["text"] for it in s.all())


def test_find_by_keyword():
    s = Store()
    assert s.find("部署脚本")


def test_add_is_deduped(tmp_path):
    s = Store(tmp_path / "t.json")
    assert s.add("同一句话") is True
    assert s.add("同一句话") is False
    assert len(s.all()) == 1


def test_blank_is_rejected(tmp_path):
    s = Store(tmp_path / "t.json")
    assert s.add("   ") is False
    assert s.all() == []
