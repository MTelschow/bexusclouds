"""FSW-PI storage: CRC'd records, rotation, corruption handling (O.3, S.5)."""
import glob
import os

import pytest

from clouds_fsw.storage import (FLAG_SATURATED, CommLog, FrameStore,
                                StorageError, read_spectra)


def _write_frames(store, n, t0=1_750_000_000.0, now=None):
    for i in range(n):
        store.write(t0 + i, [i % 65536] * 2048, 100_000,
                    FLAG_SATURATED if i == 3 else 0,
                    now=(now + i) if now is not None else None)


class TestFrameStore:
    def test_roundtrip(self, tmp_path):
        store = FrameStore(str(tmp_path), rotate_s=600)
        _write_frames(store, 5)
        store.close()
        (path,) = glob.glob(str(tmp_path / "spectra_*.csb"))
        recs = list(read_spectra(path))
        assert len(recs) == 5
        t, exp_us, flags, counts = recs[3]
        assert t == pytest.approx(1_750_000_003.0, abs=0.001)
        assert exp_us == 100_000 and flags == FLAG_SATURATED
        assert len(counts) == 2048 and counts[0] == 3

    def test_rotation_by_time(self, tmp_path):
        store = FrameStore(str(tmp_path), rotate_s=2)
        _write_frames(store, 5, now=1_750_000_000.0)   # 1 s apart, 2 s rotate
        store.close()
        files = glob.glob(str(tmp_path / "spectra_*.csb"))
        assert len(files) == 3   # records 0-1, 2-3, 4
        total = sum(len(list(read_spectra(p))) for p in files)
        assert total == 5

    def test_corrupt_record_detected(self, tmp_path):
        store = FrameStore(str(tmp_path), rotate_s=600)
        _write_frames(store, 3)
        store.close()
        (path,) = glob.glob(str(tmp_path / "spectra_*.csb"))
        data = bytearray(open(path, "rb").read())
        data[200] ^= 0xFF   # flip a count byte in record 0
        open(path, "wb").write(bytes(data))
        with pytest.raises(StorageError):
            list(read_spectra(path))
        # recovery mode (R-03): skips the bad record, keeps the rest
        good = list(read_spectra(path, strict=False))
        assert len(good) == 2

    def test_not_a_spectra_file(self, tmp_path):
        p = tmp_path / "junk.csb"
        p.write_bytes(b"JUNKJUNKJUNK")
        with pytest.raises(StorageError):
            list(read_spectra(str(p)))

    def test_truncated_tail_nonstrict(self, tmp_path):
        store = FrameStore(str(tmp_path), rotate_s=600)
        _write_frames(store, 2)
        store.close()
        (path,) = glob.glob(str(tmp_path / "spectra_*.csb"))
        data = open(path, "rb").read()
        open(path, "wb").write(data[:-100])   # power-cut mid-record
        assert len(list(read_spectra(path, strict=False))) == 1


class TestCommLog:
    def test_lines_written(self, tmp_path):
        log = CommLog(str(tmp_path), rotate_s=600)
        log.log("up", "cmd=PING", now=1_750_000_000.0)
        log.log("mcu", "event 7: seal failed", now=1_750_000_001.0)
        log.close()
        (path,) = glob.glob(str(tmp_path / "comms_*.log"))
        lines = open(path, encoding="utf-8").read().splitlines()
        assert len(lines) == 2
        assert "cmd=PING" in lines[0] and "seal failed" in lines[1]


class TestMockDataDir:
    """``--mock`` must not write to the flight path, and must not overrule a
    data directory somebody actually asked for.

    ``/data/clouds`` is root-owned on the Pi and absent on a bench laptop, so a
    mock run redirects itself. The trap is doing that unconditionally: the run
    then logs to ./clouds_data while the operator watches the directory their
    config named, and nothing says so.
    """

    def _run_main(self, monkeypatch, argv):
        from clouds_fsw import main as m

        seen = {}

        class _StubApp:
            def __init__(self, cfg, transport=None, bench_port=None):
                seen["cfg"] = cfg

            def run(self):
                pass

            def stop(self):
                pass

            def shutdown(self):
                pass

        monkeypatch.setattr(m, "FlightApp", _StubApp)
        assert m.main(argv) == 0
        return seen["cfg"]

    def test_mock_redirects_the_flight_path(self, monkeypatch):
        cfg = self._run_main(monkeypatch, ["--mock"])
        assert cfg.data_dir == os.path.abspath("./clouds_data")

    def test_config_data_dir_survives_mock(self, monkeypatch, tmp_path):
        import json

        cfg_path = tmp_path / "fsw.json"
        cfg_path.write_text(json.dumps({"data_dir": str(tmp_path / "d")}))
        cfg = self._run_main(monkeypatch, ["--mock", "--config", str(cfg_path)])
        assert cfg.data_dir == str(tmp_path / "d")

    def test_explicit_flag_wins_over_both(self, monkeypatch, tmp_path):
        cfg = self._run_main(monkeypatch,
                             ["--mock", "--data-dir", str(tmp_path / "e")])
        assert cfg.data_dir == str(tmp_path / "e")
