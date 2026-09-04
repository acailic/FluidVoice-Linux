import pytest

from fluidvoice.processing.dictionary import apply_custom_dictionary
from fluidvoice.processing.fillers import remove_filler_words
from fluidvoice.processing.slash import (MENTION_REJECTED_TOKENS,
                                         SLASH_REJECTED_TOKENS,
                                         squeeze_mentions,
                                         squeeze_slash_commands,
                                         squeeze_slash_mentions)


class TestFillers:
    def test_removes_um_uh(self):
        assert remove_filler_words("um so I uh think") == "so I think"

    def test_punctuation_trimmed(self):
        assert remove_filler_words("well, um, yes") == "well, yes"

    def test_word_boundary_respected(self):
        # "hmm" is a filler but "hammer" must survive
        assert "hammer" in remove_filler_words("the hammer is um here")

    def test_custom_list(self):
        assert remove_filler_words("blah ok", ["blah"]) == "ok"

    def test_empty_list_noop(self):
        assert remove_filler_words("um hi", []) == "um hi"


class TestDictionary:
    def test_basic_replacement(self):
        entries = [{"triggers": ["miro board"], "replacement": "Miro board"}]
        assert apply_custom_dictionary("open the miro board", entries) == "open the Miro board"

    def test_case_insensitive(self):
        entries = [{"triggers": ["jfk"], "replacement": "JFK"}]
        assert apply_custom_dictionary("flew to jfk", entries) == "flew to JFK"

    def test_word_boundary(self):
        entries = [{"triggers": ["cat"], "replacement": "dog"}]
        assert apply_custom_dictionary("the category", entries) == "the category"

    def test_longest_first(self):
        entries = [
            {"triggers": ["fluid voice"], "replacement": "FluidVoice"},
            {"triggers": ["fluid"], "replacement": "FLUID"},
        ]
        assert apply_custom_dictionary("use fluid voice now", entries) == "use FluidVoice now"

    def test_empty_noop(self):
        assert apply_custom_dictionary("hello", []) == "hello"


class TestSlashMentionSqueeze:
    """Literal `/` and `@` squeeze (chat apps) — port of Fluid-oss
    ASRService+DictationLiteralFormatting, literal forms."""

    # (input, expected) — positives
    POSITIVES = [
        ("/ fix the deploy", "/fix the deploy"),
        ("@ John Smith", "@John Smith"),
        ("please / fix it now", "please /fix it now"),
        ("/   fix", "/fix"),                       # \s+, multi-space
        ("/ Fix the deploy", "/fix the deploy"),    # token lowercased
        ("@ Jane Roe Smith", "@Jane Roe Smith"),     # 3 tokens, spacing kept
        ("I / think we should", "I /think we should"),  # upstream quirk parity
    ]

    # (input, expected) — negatives (unchanged)
    NEGATIVES = [
        "open /gerrit review",             # already joined
        "check https://example.com/path",   # URL: no whitespace after /
        "mail me at a@b.co",                # email: @ preceded by \w
        "user@ example.com",                # same lookbehind
        "and/or x",
        "he/she said",
        "24 / 7",                           # digit-first token
        "km / h",                           # single-char token
        "hello /",                          # lone trailing sigil
        "hello @",
        "/ the deploy",                     # rejected token
        "/ tmp/xyz",                        # rejected token
        "@ home now",                       # rejected -> whole match skipped
        "@ John's card",                    # possessive guard
        "at sign John",                     # spoken forms not ported
    ]

    @pytest.mark.parametrize("text,expected", POSITIVES)
    def test_positives(self, text, expected):
        assert squeeze_slash_mentions(text) == expected

    @pytest.mark.parametrize("text", NEGATIVES)
    def test_negatives_unchanged(self, text):
        assert squeeze_slash_mentions(text) == text

    def test_individual_passes(self):
        assert squeeze_slash_commands("/ fix it") == "/fix it"
        assert squeeze_slash_commands("no slashes") == "no slashes"
        assert squeeze_mentions("@ John Smith") == "@John Smith"
        assert squeeze_mentions("no sigils") == "no sigils"

    def test_disabled_by_config_is_noop(self):
        cfg = {"processing": {"slash_mention_squeeze": False}}
        assert squeeze_slash_mentions("/ fix the deploy", cfg) \
            == "/ fix the deploy"

    def test_enabled_by_default(self):
        assert squeeze_slash_mentions("/ fix it") == "/fix it"
        assert squeeze_slash_mentions("/ fix it", {}) == "/fix it"
        assert squeeze_slash_mentions(
            "/ fix it", {"processing": {"slash_mention_squeeze": True}}) \
            == "/fix it"

    def test_only_first_space_joined_mention(self):
        # the sigil joins to the name; nothing later in the phrase moves
        assert squeeze_mentions("@ John Smith please") \
            == "@John Smith please"

    def test_rejected_token_lists_match_upstream(self):
        assert len(SLASH_REJECTED_TOKENS) == 53  # upstream :101-109
        assert len(MENTION_REJECTED_TOKENS) == 25  # upstream :141-146
        for token in ("the", "tmp", "from", "without", "forward"):
            assert token in SLASH_REJECTED_TOKENS
        for token in ("home", "today", "work", "yesterday"):
            assert token in MENTION_REJECTED_TOKENS


class TestPipelineOrder:
    def test_fillers_then_dictionary_then_punctuation(self, ):
        from fluidvoice.processing import post_process
        from fluidvoice.config import DEFAULTS
        import copy
        cfg = copy.deepcopy(DEFAULTS)
        cfg["processing"]["dictionary"] = [
            {"triggers": ["fluid voice"], "replacement": "FluidVoice"}]
        out = post_process("um fluid voice literal period", cfg)
        assert out == "FluidVoice."
