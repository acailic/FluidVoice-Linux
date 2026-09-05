from fluidvoice.processing.punctuation import format_spoken_punctuation as fmt


class TestBasicPunctuation:
    def test_comma(self):
        assert fmt("buy milk literal comma then eggs") == "buy milk, then eggs"

    def test_period(self):
        assert fmt("hello literal period how are you") == "hello. how are you"

    def test_full_stop_alias(self):
        assert fmt("hello literal full stop how are you") == "hello. how are you"

    def test_question_mark(self):
        assert fmt("are you there literal question mark") == "are you there?"

    def test_exclamation(self):
        assert fmt("wow literal bang") == "wow!"

    def test_colon(self):
        assert fmt("note literal colon this is important") == "note: this is important"

    def test_semicolon(self):
        assert fmt("one literal semicolon two") == "one; two"

    def test_ellipsis(self):
        assert fmt("hmm literal ellipsis maybe") == "hmm... maybe"

    def test_no_prefix_no_change(self):
        assert fmt("buy milk comma then eggs") == "buy milk comma then eggs"

    def test_prefix_without_rule_unchanged(self):
        assert fmt("the literal banana was here") == "the literal banana was here"


class TestFormattingActions:
    def test_new_line(self):
        assert fmt("hello literal new line world") == "hello\nworld"

    def test_new_line_strips_trailing_space(self):
        assert fmt("hello literal space literal new line world") != "hello \nworld"

    def test_next_line_alias(self):
        assert fmt("hello literal next line world") == "hello\nworld"

    def test_new_paragraph(self):
        assert fmt("para one literal new paragraph para two") == "para one\n\npara two"

    def test_tab(self):
        assert fmt("a literal tab b") == "a\tb"


class TestPairedDelimiters:
    def test_parens(self):
        assert fmt("literal open paren test literal close paren") == "(test)"

    def test_brackets(self):
        assert fmt("literal open bracket x literal close bracket") == "[x]"

    def test_braces(self):
        assert fmt("literal open brace one literal close brace") == "{one}"

    def test_angle_brackets(self):
        assert fmt("literal less than sign 5 literal greater than sign") == "<5>"


class TestQuotes:
    def test_toggle_double_quote(self):
        assert fmt("he said literal quote hi literal quote") == 'he said "hi"'

    def test_explicit_open_close_quote(self):
        assert fmt('literal open quote yes literal close quote') == '"yes"'

    def test_single_quote_toggle(self):
        assert fmt("he said literal single quote hi literal single quote") == "he said 'hi'"

    def test_apostrophe_nospace(self):
        assert fmt("it literal apostrophe s") == "it's"


class TestDashesAndSymbols:
    def test_hyphen_nospace(self):
        assert fmt("well literal hyphen known") == "well-known"

    def test_dash_spaces(self):
        assert fmt("a literal dash b") == "a - b"

    def test_em_dash(self):
        assert fmt("a literal em dash b") == "a — b"

    def test_percent(self):
        assert fmt("fifty literal percent") == "fifty%"

    def test_dollar(self):
        assert fmt("literal dollar sign fifty") == "$fifty"

    def test_underscore(self):
        assert fmt("my literal underscore var") == "my_var"

    def test_hash(self):
        assert fmt("tag literal hash lol") == "tag#lol"


class TestLiveUpstreamSemantics:
    """Upstream's LIVE rule table applies rules unconditionally: the context
    gates exist only in dead code (verified against the Swift source)."""

    def test_dot_converts_everywhere(self):
        assert fmt("a literal dot") == "a."
        assert fmt("my literal dot") == "my."

    def test_at_sign_converts_everywhere(self):
        assert fmt("john literal at sign doe") == "john@doe"

    def test_dot_dot_dot_wins_over_dot(self):
        # longest-alias-first matching (upstream groups by word count desc)
        assert fmt("wait literal dot dot dot okay") == "wait... okay"

    def test_double_quote_is_a_toggle(self):
        # upstream: "double quote" shares the toggle rule with "quote"
        assert fmt('he said literal double quote hi literal double quote') == 'he said "hi"'

    def test_missing_aliases_now_present(self):
        assert fmt("a literal left parentheses b") == "a (b"
        assert fmt("a literal right parentheses b") == "a) b"
        assert fmt("literal left curly bracket x literal right curly brace") == "{x}"
        assert fmt("5 literal less than sign 6") == "5 <6"
        assert fmt("x literal plus y") == "x + y"
        assert fmt("x literal equals y") == "x = y"

    def test_invented_aliases_removed(self):
        # "angled bracket" was never an upstream alias
        assert "angled" in fmt("a literal angled bracket b")


class TestCleanups:
    def test_comma_between_symbols_dropped(self):
        # comma must be SANDWICHED between two symbols (upstream pass A)
        assert fmt("literal open paren literal comma literal close paren") == "()"

    def test_comma_beside_text_kept(self):
        # upstream keeps "hi,." - the previous neighbor is text, not a symbol
        assert fmt("hi literal comma literal period") == "hi,."

    def test_comma_before_percent_after_digit_dropped(self):
        assert fmt("50 literal comma literal percent sign") == "50%"

    def test_comma_before_percent_after_word_kept(self):
        assert fmt("fifty literal comma literal percent sign") == "fifty,%"

    def test_rule_generated_period_kept_before_newline(self):
        # pass B strips periods from ORIGINAL text only
        out = fmt("end literal period literal new line next")
        assert out == "end.\nnext"

    def test_original_text_period_stripped_before_newline(self):
        assert fmt("end. literal new line next") == "end\nnext"


class TestCaseInsensitivity:
    def test_uppercase_prefix(self):
        assert fmt("buy milk Literal comma eggs") == "buy milk, eggs"

    def test_uppercase_alias(self):
        assert fmt("hi Literal Comma there") == "hi, there"


class TestEdgeCases:
    def test_prefix_word_inside_larger_word_no_trigger(self):
        # "literalness" must not arm the engine
        assert fmt("his literalness literal comma grace") == "his literalness, grace"
        assert fmt("I love literalism") == "I love literalism"

    def test_unicode_text_passthrough(self):
        text = "čuj me molim te literal comma hvala"
        assert fmt(text) == "čuj me molim te, hvala"

    def test_email_composition(self):
        out = fmt("write to john literal at the rate example literal dot com now")
        assert out == "write to john@example.com now"

    def test_multiple_quote_pairs_toggle(self):
        out = fmt("a literal quote one literal quote b literal quote two literal quote")
        assert out == 'a "one" b "two"'

    def test_chained_commands(self):
        out = fmt("first literal comma second literal semicolon third literal period")
        assert out == "first, second; third."

    def test_prefix_at_string_start_and_end(self):
        assert fmt("literal comma") == ","
        assert fmt("hello literal comma") == "hello,"

    def test_prefix_without_following_rule_mid_sentence(self):
        text = "he said literal nothing happened next"
        assert fmt(text) == text

    def test_dot_converts_after_possessive(self):
        # live upstream has no reject-after list (that gate is dead code)
        assert fmt("my literal dot") == "my."

    def test_dot_with_digit_operand(self):
        out = fmt("room literal dot 4 literal dot 2")
        assert out == "room.4.2"

    def test_percent_after_digit_comma_cleanup(self):
        # comma before % is dropped only after an ASCII digit
        assert fmt("50 literal comma literal percent sign") == "50%"

    def test_no_rules_leaves_prefix_verbatim(self):
        text = "the literal truth matters"
        assert fmt(text) == text

    def test_double_space_collapse(self):
        out = fmt("hi literal space there literal comma friend")
        assert "  " not in out

    def test_prefix_gate_skips_when_absent(self):
        # performance gate: no prefix anywhere -> identical object content
        text = "comma period dash everywhere but no magic word"
        assert fmt(text) == text


class TestUserActionTriggers:
    """B4: user-extensible spoken formatting actions (upstream
    SpokenFormattingActionRule parity) - extra trigger aliases per action
    on top of the built-in new line/paragraph/tab/space defaults."""

    def test_extra_alias_renders_newline(self):
        out = fmt(
            "hello literal nova vrstica world",
            extra_actions={"new_line": ["nova vrstica"]})
        assert out == "hello\nworld"

    def test_extra_alias_paragraph_and_tab(self):
        out = fmt(
            "a literal nov odstavek b",
            extra_actions={"new_paragraph": ["nov odstavek"]})
        assert out == "a\n\nb"
        out = fmt(
            "a literal zamik b", extra_actions={"tab": ["zamik"]})
        assert out == "a\tb"

    def test_builtins_still_work_alongside_extras(self):
        out = fmt(
            "hello literal new line world",
            extra_actions={"new_line": ["nova vrstica"]})
        assert out == "hello\nworld"

    def test_longest_alias_wins_between_extras(self):
        # two competing extras: the 3-word alias consumes its full phrase
        out = fmt(
            "a literal nova vrstica podatki b",
            extra_actions={"new_line": ["nova vrstica", "nova vrstica podatki"]})
        assert out == "a\nb"

    def test_garbage_extras_ignored(self):
        good = {"new_line": ["nova vrstica"], "bogus_action": ["x y"],
                "tab": "not a list", "space": [42, "", None, "  "]}
        out = fmt(
            "hello literal nova vrstica world", extra_actions=good)
        assert out == "hello\nworld"
        # invalid entries never break the builtins
        assert fmt(
            "a literal tab b", extra_actions=good) == "a\tb"

    def test_extras_still_need_the_prefix(self):
        out = fmt(
            "hello nova vrstica world",
            extra_actions={"new_line": ["nova vrstica"]})
        assert out == "hello nova vrstica world"
