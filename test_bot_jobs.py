import bot_jobs


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
