"""M0 PR2/PR3 — IStorage (LocalDiskStorage) + AssetService (dedup + GC)."""

import hashlib

import pytest

from omnicast.jobengine import store
from omnicast.jobengine.storage import LocalDiskStorage
from omnicast.jobengine.assets import AssetService


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "vault.db"
    store.init_jobengine_schema(p)
    return p


def test_storage_roundtrip(tmp_path):
    st = LocalDiskStorage(str(tmp_path / "store"))
    ref = st.put_bytes(b"hello", name="x.txt", kind="audio")
    assert ref.startswith("local://") and st.exists(ref)
    assert open(st.get(ref), "rb").read() == b"hello"
    assert st.url(ref).startswith("file://")
    st.delete(ref)
    assert not st.exists(ref)


def test_storage_put_file_and_sha(tmp_path):
    src = tmp_path / "a.bin"
    src.write_bytes(b"abc")
    st = LocalDiskStorage(str(tmp_path / "s"))
    ref = st.put(str(src), kind="image")
    assert st.sha256(ref) == hashlib.sha256(b"abc").hexdigest()


def test_asset_dedup_and_gc(tmp_path, db):
    st = LocalDiskStorage(str(tmp_path / "s"))
    svc = AssetService(st, db_path=db)

    f1 = tmp_path / "1.bin"; f1.write_bytes(b"same")
    f2 = tmp_path / "2.bin"; f2.write_bytes(b"same")
    a1 = svc.register_file(str(f1), kind="image")
    a2 = svc.register_file(str(f2), kind="image")
    assert a1 == a2  # dedup by content sha256

    fm = tmp_path / "m.bin"; fm.write_bytes(b"master")
    svc.register_file(str(fm), kind="master")                         # ttl=None → never GC'd
    fi = tmp_path / "i.bin"; fi.write_bytes(b"intermediate")
    aid = svc.register_file(str(fi), kind="audio", ttl_s=-10)         # already expired
    ref = svc.get(aid)["storage_ref"]
    assert st.exists(ref)

    n = svc.gc()
    assert n == 1 and not st.exists(ref) and svc.get(aid)["state"] == "deleted"
