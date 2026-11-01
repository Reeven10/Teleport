from __future__ import annotations

import os
import random
from pathlib import Path

import pytest
from teleport_sdk.unit import collect_files, decode_state, pack_unit, unpack_unit

from contract.contract import CheckpointRecord
from teleport.migration.store import (
    CHUNK_SIZE,
    CheckpointStore,
    ChunkError,
    Reassembler,
    iter_chunks,
    sha256_hex,
)


def record_for(data: bytes, ckpt: str = "c") -> CheckpointRecord:
    return CheckpointRecord(id=ckpt, seq=1, sizeBytes=len(data), sha256=sha256_hex(data), createdAt=0)


def test_unit_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "a.txt").write_text("hello")
    files = collect_files(["data"], tmp_path)
    one = pack_unit({"b": 2, "a": 1}, files)
    two = pack_unit({"a": 1, "b": 2}, files)
    assert one == two

    dest = tmp_path / "out"
    name, raw = unpack_unit(one, files_dest=dest)
    assert decode_state(name, raw) == {"a": 1, "b": 2}
    assert (dest / "data" / "a.txt").read_text() == "hello"
    assert decode_state(*unpack_unit(pack_unit(b"\x00\x01"))) == b"\x00\x01"


def test_paths_outside_workdir_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        collect_files(["../x"], tmp_path)


def test_store_round_trip_and_changed_since(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    r1 = store.put("w", "config", pack_unit({"v": 1}))
    r2 = store.put("w", "counter", pack_unit({"count": 1}))
    assert (r1.seq, r2.seq) == (1, 2)
    assert store.put("w", "config", pack_unit({"v": 1})) == r1  # unchanged: same record, no seq bump
    assert store.verify("w", "config")
    assert (store.unit_dir("w", "config") / "unit.tar.gz").exists()

    known = store.records("w")
    assert store.changed_since("w", known) == []
    r3 = store.put("w", "counter", pack_unit({"count": 2}))
    assert store.changed_since("w", known) == [r3] and r3.seq == 3

    work, restore = tmp_path / "work", tmp_path / "restore"
    assert store.extract("w", work, restore) == ["config", "counter"]
    assert (restore / "counter" / "state.json").read_bytes() == b'{"count":2}'


def test_pack_paths_and_extract_files(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "home")
    src = tmp_path / "src"
    (src / "out").mkdir(parents=True)
    (src / "out" / "journal.txt").write_text("1\n2\n")
    rec = store.pack_paths("w", "journal", src, ["out/journal.txt"])
    assert store.pack_paths("w", "journal", src, ["out/journal.txt"]).seq == rec.seq
    store.extract("w", tmp_path / "dst", tmp_path / "restore")
    assert (tmp_path / "dst" / "out" / "journal.txt").read_text() == "1\n2\n"


def test_store_rejects_corrupt_units_and_bad_ids(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    with pytest.raises(ValueError):
        store.put("w", "c", b"not a tarball")
    with pytest.raises(ValueError):
        store.put("w", "../escape", pack_unit({}))


def test_tampered_unit_on_disk_fails_extract(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    store.put("w", "c", pack_unit({"x": 1}))
    store.unit_path("w", "c").write_bytes(pack_unit({"x": 2}))
    assert not store.verify("w", "c")
    with pytest.raises(ValueError, match="hash verification"):
        store.extract("w", tmp_path / "work", tmp_path / "restore")


def test_chunk_and_reassemble_out_of_order() -> None:
    data = os.urandom(CHUNK_SIZE * 2 + 1234)
    chunks = list(iter_chunks(data))
    assert [c.total for c in chunks] == [3, 3, 3] and len(chunks[-1].data) == 1234
    random.shuffle(chunks)
    r = Reassembler(record_for(data))
    for c in chunks + chunks[:1]:  # a duplicate is harmless
        r.add(c.index, c.total, c.data, c.sha256)
    assert r.complete and r.finalize() == data


def test_corrupted_chunk_detected_then_resent() -> None:
    data = os.urandom(5000)
    chunks = list(iter_chunks(data, chunk_size=1024))
    r = Reassembler(record_for(data), chunk_size=1024)
    bad = bytearray(chunks[2].data)
    bad[0] ^= 0xFF
    with pytest.raises(ChunkError, match="chunk 2 failed SHA-256"):
        r.add(2, chunks[2].total, bytes(bad), chunks[2].sha256)
    for c in chunks[:4]:
        r.add(c.index, c.total, c.data, c.sha256)
    assert r.missing() == [4]
    with pytest.raises(ChunkError, match="missing chunks"):
        Reassembler(record_for(data), chunk_size=1024).finalize()
    last = chunks[4]
    r.add(last.index, last.total, last.data, last.sha256)
    assert r.finalize() == data


def test_whole_checkpoint_hash_mismatch_detected() -> None:
    data = os.urandom(3000)
    wrong = record_for(data).model_copy(update={"sha256": sha256_hex(b"other")})
    r = Reassembler(wrong, chunk_size=1024)
    for c in iter_chunks(data, chunk_size=1024):
        r.add(c.index, c.total, c.data, c.sha256)
    with pytest.raises(ChunkError, match="checkpoint SHA-256 mismatch"):
        r.finalize()


def test_chunks_from_file(tmp_path: Path) -> None:
    path = tmp_path / "unit"
    path.write_bytes(os.urandom(CHUNK_SIZE + 10))
    assert b"".join(c.data for c in iter_chunks(path)) == path.read_bytes()


def test_checkpoints_keep_landing_while_a_migration_reads_them(tmp_path: Path) -> None:
    """A job checkpointing every few ms while the migration snapshots the same unit: on Windows an
    unlocked read made the save fail with WinError 5, the job crashed and the migration rolled back."""
    import threading

    store = CheckpointStore(tmp_path)
    store.put("wl", "counter", pack_unit({"count": 0}, []))
    errors: list[BaseException] = []
    stop = threading.Event()

    def writer() -> None:
        try:
            for i in range(300):
                store.put("wl", "counter", pack_unit({"count": i + 1}, []))
        except BaseException as e:  # noqa: BLE001 - the test reports whatever broke
            errors.append(e)
        finally:
            stop.set()

    t = threading.Thread(target=writer)
    t.start()
    reads = 0
    while not stop.is_set():
        pair = store.read_with_record("wl", "counter")
        assert pair is not None and sha256_hex(pair[0]) == pair[1].sha256  # always a consistent pair
        reads += 1
    t.join()
    assert not errors, errors
    assert reads > 0
