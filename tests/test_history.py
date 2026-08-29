import threading

from portmaster import history, registry


def test_history_append_and_read(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "HOME", tmp_path)
    pid = "testproj"
    history.append(pid, {"duration_s": 2.1, "result": "running"})
    history.append(pid, {"duration_s": 1.9, "result": "running"})

    entries = history.read(pid, limit=10)
    assert len(entries) == 2
    assert entries[0]["duration_s"] == 2.1
    assert "timestamp" in entries[0]


def test_history_invalid_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "HOME", tmp_path)
    # Intento de path traversal no debe explotar ni escribir fuera
    history.append("../../evil", {"data": "bad"})
    assert history.read("../../evil") == []


def test_history_concurrent_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "HOME", tmp_path)
    pid = "concurrentproj"

    def worker(idx):
        for i in range(10):
            history.append(pid, {"worker": idx, "i": i})

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    entries = history.read(pid, limit=100)
    assert len(entries) == 50
