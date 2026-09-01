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


class TestContextRules:
    def test_dot_in_domain(self):
        assert fmt("example literal dot com") == "example.com"

    def test_dot_rejected_after_article(self):
        # "a dot" without path context stays literal
        assert fmt("a literal dot") == "a literal dot"

    def test_slash_in_path(self):
        assert fmt("usr literal slash bin") == "usr/bin"

    def test_at_the_rate(self):
        assert fmt("name literal at the rate gmail literal dot com") == "name@gmail.com"

    def test_at_sign_needs_app_hint(self):
        assert fmt("john literal at sign doe") == "john literal at sign doe"
        assert fmt("john literal at sign doe", app_hint="Slack") == "john@doe"


class TestCleanups:
    def test_comma_before_generated_period_dropped(self):
        # "hi , ." -> the generated comma next to generated period disappears
        out = fmt("hi literal comma literal period")
        assert out == "hi."

    def test_period_before_newline_dropped(self):
        out = fmt("end literal period literal new line next")
        assert out == "end\nnext"


class TestCaseInsensitivity:
    def test_uppercase_prefix(self):
        assert fmt("buy milk Literal comma eggs") == "buy milk, eggs"

    def test_uppercase_alias(self):
        assert fmt("hi Literal Comma there") == "hi, there"
