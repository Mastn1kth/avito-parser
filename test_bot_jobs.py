import bot_jobs
import pytest


@pytest.fixture(autouse=True)
def isolate_watch_targets(monkeypatch, tmp_path):
    monkeypatch.setattr(bot_jobs, "WATCH_TARGETS", tmp_path / "bot-watch-targets.json")


def test_watch_job_reports_immediate_failure(monkeypatch, tmp_path):
    (tmp_path / "avito.py").write_text(
        'print(\'{"event":"FATAL","error":"invalid search"}\', flush=True)\n', encoding="utf-8"
    )
    monkeypatch.setattr(bot_jobs, "ROOT", tmp_path)
    jobs = bot_jobs.Jobs()

    assert jobs.start_watch(["missing"]) is False
    assert jobs.last_watch_error == "invalid search"
    assert jobs.watch_running() is False


def test_watch_job_confirms_start_and_stops(monkeypatch, tmp_path):
    (tmp_path / "avito.py").write_text(
        'import time\nprint(\'{"event":"WATCH"}\', flush=True)\n'
        'while True:\n    time.sleep(1)\n', encoding="utf-8"
    )
    monkeypatch.setattr(bot_jobs, "ROOT", tmp_path)
    jobs = bot_jobs.Jobs()

    try:
        assert jobs.start_watch(["example"]) is True
        assert jobs.watch_running() is True
    finally:
        jobs.stop_watch()
    assert jobs.watch_running() is False


def test_finished_watch_is_reported_once():
    class ExitedProcess:
        returncode = 1

        def poll(self):
            return self.returncode

    jobs = bot_jobs.Jobs()
    jobs.watch = ExitedProcess()
    jobs.watch_names = ["phones"]

    assert "phones" in jobs.take_stopped_watch()
    assert jobs.take_stopped_watch() is None


def test_watch_selection_resumes_after_server_restart(monkeypatch, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "searches").mkdir()
    (tmp_path / "searches" / "pcs.json").write_text("{}", encoding="utf-8")
    (tmp_path / "avito.py").write_text(
        'import time\nprint(\'{"event":"WATCH"}\', flush=True)\n'
        'while True:\n    time.sleep(1)\n', encoding="utf-8"
    )
    monkeypatch.setattr(bot_jobs, "ROOT", tmp_path)
    monkeypatch.setattr(bot_jobs, "WATCH_TARGETS", tmp_path / "data" / "bot-watch-targets.json")
    first = bot_jobs.Jobs()
    assert first.start_watch(["pcs"])
    first.stop_watch(preserve_selection=True)
    second = bot_jobs.Jobs()
    try:
        assert second.resume_watch()
        assert second.watch_names == ["pcs"]
    finally:
        second.stop_watch()
    assert not bot_jobs.WATCH_TARGETS.exists()


def test_iphone_mode_launch_and_resume_without_search_files(monkeypatch, tmp_path):
    (tmp_path / "iphone_mode.py").write_text(
        'import time\nprint(\'{"event":"WATCH"}\', flush=True)\n'
        'while True:\n    time.sleep(1)\n', encoding="utf-8")
    monkeypatch.setattr(bot_jobs, "ROOT", tmp_path)
    jobs = bot_jobs.Jobs()
    assert jobs.start_watch(["mode-iphones"])
    jobs.stop_watch(preserve_selection=True)
    try:
        assert jobs.resume_watch()
        assert jobs.watch_names == ["mode-iphones"]
    finally:
        jobs.stop_watch()
