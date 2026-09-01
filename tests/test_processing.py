from fluidvoice.processing.dictionary import apply_custom_dictionary
from fluidvoice.processing.fillers import remove_filler_words


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
