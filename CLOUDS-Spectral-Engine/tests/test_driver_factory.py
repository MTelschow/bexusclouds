"""Driver factory: kind resolution, per-kind dispatch, platform guards.

Hardware-free throughout - the point is that ``open_driver`` picks the right
class and that a wrong ``kind`` fails loudly, without loading a vendor library.
"""
import sys

import pytest

from spectro.driver import KINDS, open_driver, resolve_kind
from spectro.mock_driver import MockDriver

KIND_ENV = "CLOUDS_SPECTRO_KIND"


@pytest.fixture(autouse=True)
def _no_kind_env(monkeypatch):
    monkeypatch.delenv(KIND_ENV, raising=False)


class TestResolveKind:
    def test_default_is_std(self):
        assert resolve_kind() == "std"

    def test_explicit_wins_over_env(self, monkeypatch):
        monkeypatch.setenv(KIND_ENV, "std")
        assert resolve_kind("edu") == "edu"

    def test_env_used_when_unset(self, monkeypatch):
        monkeypatch.setenv(KIND_ENV, "edu")
        assert resolve_kind() == "edu"
        assert resolve_kind(None) == "edu"

    def test_case_and_whitespace_tolerant(self):
        assert resolve_kind("  EDU ") == "edu"

    @pytest.mark.parametrize("bad", ["duo", "std2", "STD ,edu", "x"])
    def test_unknown_kind_raises(self, bad):
        with pytest.raises(ValueError, match="unknown spectrometer kind"):
            resolve_kind(bad)

    def test_bad_env_raises(self, monkeypatch):
        monkeypatch.setenv(KIND_ENV, "nope")
        with pytest.raises(ValueError):
            resolve_kind()


class TestOpenDriver:
    def test_mock_ignores_kind(self):
        # --mock must stay hardware-free whatever kind is configured
        assert isinstance(open_driver(mock=True), MockDriver)
        assert isinstance(open_driver(mock=True, kind="edu"), MockDriver)

    def test_std_selects_duo_driver(self):
        from spectro.eureca_driver import EurecaDriver
        assert type(open_driver(kind="std")) is EurecaDriver

    def test_edu_selects_edu_driver(self):
        from spectro.eureca_edu_driver import EurecaEduDriver
        assert type(open_driver(kind="edu")) is EurecaEduDriver

    def test_env_selects_edu_driver(self, monkeypatch):
        from spectro.eureca_edu_driver import EurecaEduDriver
        monkeypatch.setenv(KIND_ENV, "edu")
        assert type(open_driver()) is EurecaEduDriver

    def test_unknown_kind_raises_before_loading_a_library(self):
        with pytest.raises(ValueError):
            open_driver(kind="duo")

    def test_all_kinds_construct(self):
        # construction must never touch the vendor library (that is connect()'s job)
        for kind in KINDS:
            assert open_driver(kind=kind) is not None


@pytest.mark.skipif(sys.platform == "win32",
                    reason="the EDU DLL is present and loadable on Windows")
class TestEduPlatformGuard:
    def test_edu_connect_raises_clear_error_off_windows(self):
        from spectro.driver import DriverError
        drv = open_driver(kind="edu")
        with pytest.raises(DriverError, match="Windows-only"):
            drv.connect()


class TestFswConfigKind:
    """The flight config must reject a bad kind at load, not at first connect."""

    def test_default_is_the_duo(self):
        from clouds_fsw.config import FswConfig
        assert FswConfig().spectro_kind == "std"

    def test_valid_kind_accepted(self):
        from clouds_fsw.config import FswConfig
        assert FswConfig.load(None, spectro_kind="edu").spectro_kind == "edu"

    def test_bad_kind_rejected_at_load(self):
        from clouds_fsw.config import FswConfig
        with pytest.raises(ValueError, match="unknown spectrometer kind"):
            FswConfig.load(None, spectro_kind="duo")


class TestEurecaLibResolution:
    """The Duo driver must pick the right library name per platform."""

    def test_library_name_matches_platform(self):
        from spectro import eureca_driver as ed
        expected = "libe9u_LSMD_x64.dll" if sys.platform == "win32" else "libe9u_LSMD.so"
        assert ed._LIB_NAME == expected

    def test_env_override_is_honoured(self, monkeypatch, tmp_path):
        from spectro import eureca_driver as ed
        env = "CLOUDS_E9U_DLL_DIR" if sys.platform == "win32" else "CLOUDS_E9U_LIB_DIR"
        (tmp_path / ed._LIB_NAME).write_bytes(b"not a real library")
        monkeypatch.setenv(env, str(tmp_path))
        assert ed._resolve_lib_dir() == str(tmp_path)

    def test_env_pointing_at_nothing_is_ignored(self, monkeypatch, tmp_path):
        from spectro import eureca_driver as ed
        env = "CLOUDS_E9U_DLL_DIR" if sys.platform == "win32" else "CLOUDS_E9U_LIB_DIR"
        monkeypatch.setenv(env, str(tmp_path))       # empty dir, no library
        assert ed._resolve_lib_dir() != str(tmp_path)
