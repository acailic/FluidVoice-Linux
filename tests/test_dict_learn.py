"""Dictionary auto-learning: extraction tables, store, pending, merge.

Mirrors the plan in specs/a8b2afa6_dict-auto-learn.md (upstream Fluid
1.6.3 semantics verified against altic-dev/Fluid-oss @ ae9b71a).
"""
from __future__ import annotations

import json

import pytest

from fluidvoice import paths
from fluidvoice.config import DEFAULTS
from fluidvoice.processing import dict_learn
from fluidvoice.processing.dictionary import apply_custom_dictionary


class TestExtractCandidates:
    @pytest.mark.parametrize("old,new,expected", [
        # positives
        ("open the miro board app", "open the Miro board app",
         [("miro board", "Miro board")]),  # case-only, canonical
        ("please send the flud report", "please send the fluid report",
         [("flud", "fluid")]),
        ("check gnu plot output", "check gnuplot output",
         [("gnu plot", "gnuplot")]),  # 2→1 tokens (word merge)
        ("its say it ermano again", "its SayItErmano again",
         [("say it ermano", "SayItErmano")]),  # case-only 3 tokens, merged
        ("send it to john smith", "send it to John Smith",
         [("john smith", "John Smith")]),  # adjacent case fixes = one op
        ("mark it k", "mark it okay", []),  # <2 chars on one side (upstream)
        # negatives
        ("hi , there", "hi, there", []),  # punctuation-only span
        ("meeting at 3 pm", "meeting at 3PM", []),  # numeric token
        ("so um yeah", "so hmm yeah", []),  # filler tokens both sides
        ("miro  board", "miro board", []),  # spacing-only (no op after split)
        ("Miro, board", "Miro board", []),  # punctuation/spacing-only
        ("i want to go now", "we need to leave now",
         []),  # scattered rewrite = editing
        ("fix it", "fix the broken thing now", []),  # new side 4 tokens
        ("same text here", "same text here", []),  # no change
    ])
    def test_table(self, old, new, expected):
        assert dict_learn.extract_candidates(old, new) == expected

    def test_repeated_pair_within_one_entry_collapses(self):
        # difflib splits this into two replace ops with the same pair;
        # an entry is one correction event -> one candidate
        assert dict_learn.extract_candidates(
            "flud then flud", "fluid then fluid") == [("flud", "fluid")]

    def test_custom_filler_list_honored(self):
        # "um"/"hmm" not in the passed list -> the pair qualifies
        # (DEFAULT_FILLERS would reject both sides)
        assert dict_learn.extract_candidates(
            "so um yeah", "so hmm yeah", fillers=["er"]) == [("um", "hmm")]

    def test_case_only_expansion_stops_at_three_words(self):
        # "the quick brown" is already 3 words: no right-context expansion
        assert dict_learn.extract_candidates(
            "the quick brown fox", "The Quick Brown fox") == \
            [("the quick brown", "The Quick Brown")]

    def test_none_inputs(self):
        assert dict_learn.extract_candidates(None, "x y") == []
        assert dict_learn.extract_candidates("x y", None) == []


class TestStore:
    def test_load_missing_file_is_empty(self, tmp_path):
        p = tmp_path / "s.json"
        assert dict_learn.load_store(p) == {"dismissed": [], "accepted": []}

    def test_load_corrupt_file_is_empty(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text("{not json", encoding="utf-8")
        assert dict_learn.load_store(p) == {"dismissed": [], "accepted": []}

    def test_load_non_dict_is_empty(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text('["x"]', encoding="utf-8")
        assert dict_learn.load_store(p) == {"dismissed": [], "accepted": []}

    def test_save_load_round_trip(self, tmp_path):
        p = tmp_path / "s.json"
        store = {"dismissed": [["miro board", "Miro board"]],
                 "accepted": []}
        dict_learn.save_store(p, store)
        assert dict_learn.load_store(p) == store
        assert json.loads(p.read_text(encoding="utf-8")) == {
            "dismissed": [["miro board", "Miro board"]], "accepted": []}

    def test_dismiss_and_record_accepted_resolve_path_at_call_time(
            self, tmp_path, monkeypatch):
        spath = tmp_path / "dictionary-suggestions.json"
        monkeypatch.setattr(paths, "dictionary_suggestions_file",
                            lambda: spath)
        dict_learn.dismiss("miro board", "Miro board")
        dict_learn.dismiss("miro board", "Miro board")  # dedupe
        dict_learn.record_accepted("flud voice", "fluid voice")
        assert dict_learn.load_store(spath) == {
            "dismissed": [["miro board", "Miro board"]],
            "accepted": [["flud voice", "fluid voice"]]}


def _entry(ts, edited_from, text):
    return {"ts": ts, "text": text, "edited_from": edited_from}


MIRO_PAIR = (_entry(1.0, "open the miro board app",
                    "open the Miro board app"),
             _entry(2.0, "open the miro board now",
                    "open the Miro board now"))


class TestPendingSuggestions:
    def test_threshold_two(self):
        entries = [_entry(1.0, "please send the flud report",
                          "please send the fluid report")]
        assert dict_learn.pending_suggestions(DEFAULTS, entries) == []
        entries.append(_entry(2.0, "the flud report again",
                              "the fluid report again"))
        got = dict_learn.pending_suggestions(DEFAULTS, entries)
        assert got == [{"heard": "flud", "corrected": "fluid", "count": 2}]

    def test_min_occurrences_override(self):
        entries = [_entry(1.0, "please send the flud report",
                          "please send the fluid report")]
        assert dict_learn.pending_suggestions(DEFAULTS, entries,
                                              min_occurrences=1) == \
            [{"heard": "flud", "corrected": "fluid", "count": 1}]

    def test_pair_twice_within_one_entry_counts_once(self):
        entries = [_entry(1.0, "flud then flud", "fluid then fluid")]
        assert dict_learn.pending_suggestions(DEFAULTS, entries,
                                              min_occurrences=1)[0][
            "count"] == 1

    def test_sorted_by_count_then_recency(self):
        entries = [
            _entry(1.0, "send the flud report", "send the fluid report"),
            _entry(2.0, "flud again", "fluid again"),
            _entry(3.0, "open the miro board", "open the Miro board"),
            _entry(4.0, "open the miro board app",
                   "open the Miro board app"),
        ]
        got = dict_learn.pending_suggestions(DEFAULTS, entries,
                                             min_occurrences=2)
        # equal counts: the pair seen in the most recent entry sorts first
        assert [(s["heard"], s["count"]) for s in got] == \
            [("miro board", 2), ("flud", 2)]
        entries = [
            _entry(1.0, "send the flud report", "send the fluid report"),
            _entry(2.0, "open the miro board", "open the Miro board"),
            _entry(3.0, "open the miro board app",
                   "open the Miro board app"),
            _entry(4.0, "flud again", "fluid again"),
        ]
        got = dict_learn.pending_suggestions(DEFAULTS, entries,
                                             min_occurrences=2)
        assert [(s["heard"], s["count"]) for s in got] == \
            [("flud", 2), ("miro board", 2)]

    def test_dictionary_trigger_suppressed_case_insensitively(self):
        import copy
        cfg = copy.deepcopy(DEFAULTS)
        cfg["processing"]["dictionary"] = [
            {"triggers": ["Miro Board"], "replacement": "Miro board"}]
        got = dict_learn.pending_suggestions(cfg, list(MIRO_PAIR))
        assert got == []  # trigger already saved (case-insensitive)
        # a different heard for the same replacement still suggests
        got = dict_learn.pending_suggestions(cfg, [
            _entry(1.0, "miro boards", "Miro Boards"),
            _entry(2.0, "miro boards", "Miro Boards")])
        assert got == [{"heard": "miro boards", "corrected": "Miro Boards",
                        "count": 2}]

    def test_dismissed_and_accepted_never_resuggested(self):
        entries = list(MIRO_PAIR)
        assert dict_learn.pending_suggestions(
            DEFAULTS, entries,
            store={"dismissed": [["miro board", "Miro board"]],
                   "accepted": []}) == []
        assert dict_learn.pending_suggestions(
            DEFAULTS, entries,
            store={"dismissed": [],
                   "accepted": [["miro board", "Miro board"]]}) == []

    def test_dismiss_permanent_across_save_load_restart(
            self, tmp_path, monkeypatch):
        spath = tmp_path / "dictionary-suggestions.json"
        monkeypatch.setattr(paths, "dictionary_suggestions_file",
                            lambda: spath)
        dict_learn.dismiss("miro board", "Miro board")
        # simulated restart: decisions come from the reloaded store
        store = dict_learn.load_store(spath)
        assert dict_learn.pending_suggestions(DEFAULTS, list(MIRO_PAIR),
                                              store=store) == []

    def test_fillers_from_config_honored(self):
        import copy
        cfg = copy.deepcopy(DEFAULTS)
        cfg["processing"]["filler_words"] = ["er"]
        entries = [_entry(1.0, "so um yeah", "so hmm yeah"),
                   _entry(2.0, "so um please", "so hmm please")]
        got = dict_learn.pending_suggestions(cfg, entries,
                                             min_occurrences=2)
        assert got == [{"heard": "um", "corrected": "hmm", "count": 2}]

    def test_entries_without_edited_from_ignored(self):
        assert dict_learn.pending_suggestions(
            DEFAULTS, [{"ts": 1.0, "text": "plain"}]) == []


class TestAcceptMerge:
    def test_appends_new_entry(self):
        assert dict_learn.accept_merge([], "flud voice", "fluid voice") == [
            {"triggers": ["flud voice"], "replacement": "fluid voice"}]

    def test_same_replacement_gains_trigger_once(self):
        dictionary = [{"triggers": ["slack"], "replacement": "Slack Channel"}]
        merged = dict_learn.accept_merge(dictionary, "slack channel",
                                         "slack channel")
        assert merged == [{"triggers": ["slack", "slack channel"],
                           "replacement": "Slack Channel"}]
        # duplicate trigger (case-insensitive) not added
        merged2 = dict_learn.accept_merge(merged, "Slack Channel",
                                          "Slack Channel")
        assert merged2 == merged

    def test_input_not_mutated(self):
        dictionary = [{"triggers": ["slack"], "replacement": "Slack Channel"}]
        dict_learn.accept_merge(dictionary, "slack channel", "slack channel")
        assert dictionary == [{"triggers": ["slack"],
                               "replacement": "Slack Channel"}]

    def test_accept_end_to_end_rewrites_old_form(self):
        merged = dict_learn.accept_merge([], "miro board", "Miro board")
        assert apply_custom_dictionary(
            "open the miro board app", merged) == "open the Miro board app"
