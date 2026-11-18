"""Pins `voiceloop.part_runs`: a partial or empty run is never complete (ASK-4327, ASK-5411).

Pure function, no files, no corpus. Control first: a full run is complete.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from voiceloop import part_runs  # noqa: E402


def test_full_run_is_complete():
    r = part_runs.assess({"a": {"ran": 1, "of": 1}, "b": (15, 15)})
    assert r.complete and r.reasons() == []


def test_ran_zero_is_not_complete():
    r = part_runs.assess({"a": {"ran": 1, "of": 1}, "critic": {"ran": 0, "of": 15}})
    assert not r.complete and r.zero == [("critic", 15)]


def test_ran_zero_of_zero_is_zero_not_complete():
    r = part_runs.assess({"critic": {"ran": 0, "of": 0}})
    assert not r.complete and r.zero == [("critic", 0)]


def test_partial_is_not_complete():
    r = part_runs.assess({"critic": (8, 15)})
    assert not r.complete and r.partial == [("critic", 8, 15)] and not r.zero


def test_empty_is_not_complete():
    for parts in ({}, None):
        r = part_runs.assess(parts)
        assert r.empty and not r.complete


def test_unreadable_count_reads_as_zero():
    for bad in ({"ran": "1", "of": 1}, {"ran": True, "of": 1}, {}, None, "ran", (1,)):
        r = part_runs.assess({"a": bad})
        assert not r.complete and r.zero, bad
