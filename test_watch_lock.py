import pytest

from watch_lock import watch_locks


def test_overlapping_watches_cannot_open_same_search(tmp_path):
    with watch_locks(tmp_path, ["phones", "laptops"]):
        with pytest.raises(RuntimeError, match="phones"):
            with watch_locks(tmp_path, ["phones"]):
                pass
        with watch_locks(tmp_path, ["monitors"]):
            pass
    with watch_locks(tmp_path, ["phones"]):
        pass
