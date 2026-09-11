"""The frontmatter parser and serializer: the flat YAML subset of Implementation Decisions 2."""

import re
import unittest

from tests.paths import HARNESS_ROOT
from wayline import frontmatter
from wayline.frontmatter import FrontmatterError, dump_document, load_document, parse, serialize


def brief_example_ticket():
    """The ticket example of BRIEF.md Section 8.2, as document text with a body."""
    text = (HARNESS_ROOT / "BRIEF.md").read_text(encoding="utf-8")
    section = text[text.index("### 8.2 "):]
    block = re.search(r"```yaml\n(.*?)```", section, re.S).group(1)
    return "---\n" + block + "---\n\n## Demo\n\nA table with three seeds.\n"


class ScalarTest(unittest.TestCase):
    def test_scalar_kinds(self):
        got = parse(
            "a: 17\nb: -3\nc: true\nd: false\ne: null\nf: bare words here\n"
            'g: "quoted: with # both"\nh: 0.83\ni: 1e-05\nj: SPEC.md#claim-2\n'
        )
        self.assertEqual(got, {
            "a": 17, "b": -3, "c": True, "d": False, "e": None, "f": "bare words here",
            "g": "quoted: with # both", "h": 0.83, "i": 1e-05, "j": "SPEC.md#claim-2",
        })
        self.assertIs(type(got["a"]), int)
        self.assertIs(type(got["c"]), bool)

    def test_quoted_escapes(self):
        got = parse(r'a: "line\nbreak \"q\" back\\slash tab\t"')
        self.assertEqual(got["a"], 'line\nbreak "q" back\\slash tab\t')
        self.assertEqual(parse(r'a: "é中"'), {"a": "é中"})
        with self.assertRaises(FrontmatterError):
            parse(r'a: "\u00zz"')
        with self.assertRaises(FrontmatterError):
            parse(r'a: "\q"')

    def test_bare_string_may_end_with_a_bracket(self):
        self.assertEqual(parse("a: see figure 2]\n"), {"a": "see figure 2]"})

    def test_surrogate_pairs_and_lone_surrogates(self):
        self.assertEqual(parse(r'a: "😀"'), {"a": "\U0001f600"})
        self.assertEqual(parse(serialize({"a": "\U0001f600"})), {"a": "\U0001f600"})
        for text in [r'a: "\ud83d"', r'a: "\ud83dx"', r'a: "\ude00"', r'a: "\ud83dA"']:
            with self.subTest(text=text):
                with self.assertRaises(FrontmatterError):
                    parse(text)
        with self.assertRaises(FrontmatterError):
            serialize({"a": "\ud83d"})

    def test_only_newline_ends_a_line(self):
        """U+2028, U+0085, a lone carriage return: data inside a line, never a line end."""
        for value in ["x y", "x y", "x\x85y", "x\ry", "x\x0cy", "x y #"]:
            with self.subTest(value=repr(value)):
                text = serialize({"a": value, "b": 1})
                self.assertEqual(text.count("\n"), 2)
                self.assertNotIn(value[1], text)
                self.assertEqual(parse(text), {"a": value, "b": 1})
        self.assertEqual(parse("a: x y\nb: 1\n"), {"a": "x y", "b": 1})
        self.assertEqual(parse('a: "x y #"\nb: 1\n'), {"a": "x y #", "b": 1})
        self.assertEqual(parse("a: 1\r\nb: 2\r\n"), {"a": 1, "b": 2})

    def test_empty_value_is_null(self):
        self.assertEqual(parse("a:\nb: 1\n"), {"a": None, "b": 1})

    def test_key_order_is_kept(self):
        self.assertEqual(list(parse("z: 1\na: 2\nm: 3\n")), ["z", "a", "m"])

    def test_yaml_lookalikes_stay_strings(self):
        got = parse("a: yes\nb: True\nc: ~\nd: 1_000\ne: 0x10\n")
        self.assertEqual(got, {"a": "yes", "b": "True", "c": "~", "d": "1_000", "e": "0x10"})


class FlowTest(unittest.TestCase):
    def test_flow_list(self):
        got = parse('a: [12, 14]\nb: []\nc: [experiments/ablation_b/, "x, y", true, null]\n')
        self.assertEqual(got, {"a": [12, 14], "b": [], "c": ["experiments/ablation_b/", "x, y", True, None]})

    def test_flow_map(self):
        got = parse("a: {gpu: 1, cpu: 8, ram_gb: 32}\nb: {}\nc: {reports: auroc_b, expected_direction: down}\n")
        self.assertEqual(got, {"a": {"gpu": 1, "cpu": 8, "ram_gb": 32}, "b": {}, "c": {"reports": "auroc_b", "expected_direction": "down"}})

    def test_trailing_comma_is_tolerated(self):
        self.assertEqual(parse("a: [1, 2, ]\n"), {"a": [1, 2]})


class BlockTest(unittest.TestCase):
    def test_block_map_of_scalars_and_lists(self):
        got = parse('acceptance:\n  machine: ["test -f x", "python check.py"]\n  quality: [Is it isolated?]\n  note: fine\n')
        self.assertEqual(got, {"acceptance": {"machine": ["test -f x", "python check.py"], "quality": ["Is it isolated?"], "note": "fine"}})

    def test_block_list(self):
        got = parse("touches:\n  - experiments/a/\n  - results/a/\n  - 3\n")
        self.assertEqual(got, {"touches": ["experiments/a/", "results/a/", 3]})

    def test_blank_and_comment_lines_inside_a_block(self):
        got = parse("a:\n  x: 1\n\n  # a comment\n  y: 2\nb: 3\n")
        self.assertEqual(got, {"a": {"x": 1, "y": 2}, "b": 3})

    def test_any_consistent_indent_width(self):
        self.assertEqual(parse("a:\n    x: 1\n    y: 2\n"), {"a": {"x": 1, "y": 2}})


class CommentTest(unittest.TestCase):
    def test_trailing_and_full_line_comments(self):
        got = parse("# leading\na: 3   # 1..5\nb: [x, y]  # list\n\n# between\nc: {k: v} # map\n")
        self.assertEqual(got, {"a": 3, "b": ["x", "y"], "c": {"k": "v"}})

    def test_hash_without_space_is_not_a_comment(self):
        self.assertEqual(parse("a: research/SPEC.md#claim-2\n"), {"a": "research/SPEC.md#claim-2"})


class RejectionTest(unittest.TestCase):
    def assert_rejected(self, text, line, fragment):
        with self.assertRaises(FrontmatterError) as caught:
            parse(text)
        self.assertEqual(caught.exception.line, line, str(caught.exception))
        self.assertIn(fragment, str(caught.exception))
        self.assertTrue(str(caught.exception).startswith("line %d:" % line))

    def test_anchor(self):
        self.assert_rejected("a: 1\nb: &x 2\n", 2, "anchor")

    def test_alias(self):
        self.assert_rejected("a: *x\n", 1, "alias")

    def test_multi_line_scalars(self):
        self.assert_rejected("a: 1\nb: |\n  text\n", 2, "multi-line")
        self.assert_rejected("a: >\n  text\n", 1, "multi-line")

    def test_deeper_nesting(self):
        self.assert_rejected("a:\n  b:\n    c: 1\n", 3, "deeper")

    def test_nested_flow(self):
        self.assert_rejected("a: [1, [2]]\n", 1, "nested")
        self.assert_rejected("a: {k: {j: 1}}\n", 1, "nested")

    def test_block_list_of_collections(self):
        self.assert_rejected("a:\n  - [1, 2]\n", 2, "nested")

    def test_mixed_block_children(self):
        self.assert_rejected("a:\n  x: 1\n  - y\n", 3, "mix")

    def test_inconsistent_indent(self):
        self.assert_rejected("a:\n  x: 1\n y: 2\n", 3, "indent")

    def test_tabs(self):
        self.assert_rejected("a:\n\tx: 1\n", 2, "tab")

    def test_duplicate_key(self):
        self.assert_rejected("a: 1\nb: 2\na: 3\n", 3, "duplicate")
        self.assert_rejected("a:\n  x: 1\n  x: 2\n", 3, "duplicate")
        self.assert_rejected("a: {x: 1, x: 2}\n", 1, "duplicate")

    def test_unterminated_quote_and_flow(self):
        self.assert_rejected('a: "open\n', 1, "quote")
        self.assert_rejected("a: [1, 2\n", 1, "flow list")
        self.assert_rejected("a: {k: v\n", 1, "flow map")

    def test_single_quotes(self):
        self.assert_rejected("a: 'x'\n", 1, "double")

    def test_bare_string_with_colon_space(self):
        self.assert_rejected("a: b: c\n", 1, "': '")

    def test_indented_line_without_parent(self):
        self.assert_rejected("  a: 1\n", 1, "indent")

    def test_line_without_key(self):
        self.assert_rejected("just words\n", 1, "key")
        self.assert_rejected("bad key: 1\n", 1, "key")

    def test_stray_text_after_flow(self):
        self.assert_rejected("a: [1] x\n", 1, "after")

    def test_document_without_frontmatter(self):
        with self.assertRaises(FrontmatterError):
            load_document("no frontmatter\n")
        with self.assertRaises(FrontmatterError):
            load_document("---\na: 1\nbody without a closing fence\n")

    def test_line_numbers_count_from_the_opening_fence(self):
        with self.assertRaises(FrontmatterError) as caught:
            load_document("---\na: 1\nb: &x 1\n---\n")
        self.assertEqual(caught.exception.line, 3)
        with self.assertRaises(FrontmatterError) as caught:
            load_document("---\na: 1\nb: 2\r\nc: &x 1\n---\n")
        self.assertEqual(caught.exception.line, 4)

    def test_missing_closing_fence_names_the_last_line(self):
        with self.assertRaises(FrontmatterError) as caught:
            load_document("---\na: 1\nbody\n")
        self.assertEqual(caught.exception.line, 3)
        with self.assertRaises(FrontmatterError) as caught:
            load_document("---\na: 1")
        self.assertEqual(caught.exception.line, 2)


class SerializeTest(unittest.TestCase):
    def assert_round_trip(self, value):
        text = serialize({"v": value})
        self.assertEqual(parse(text), {"v": value}, text)
        return text

    def test_scalars_and_quoting(self):
        for value in [0, -7, 1.5, True, False, None, "", " padded ", "17", "true", "null", "~", "1.5",
                      "a: b", "ends with:", "with # hash", "#lead", "[bracket", "{brace", '"quoted"',
                      "back\\slash", "new\nline", "tab\there", "- dash", "-", "&anchor", "*alias",
                      "|pipe", ">gt", "!tag", "%pct", "@at", "`tick", "'single'", "a, b", "yes", "Null",
                      "research/SPEC.md#claim-2", "plain words", "-x", "unicode é ü 中"]:
            with self.subTest(value=value):
                self.assert_round_trip(value)

    def test_bare_when_safe(self):
        self.assertEqual(serialize({"title": "Ablate the term on B", "n": 3, "f": 0.9, "b": True, "z": None}),
                         "title: Ablate the term on B\nn: 3\nf: 0.9\nb: true\nz: null\n")

    def test_collections(self):
        self.assert_round_trip([1, "a, b", None, "x"])
        self.assert_round_trip([])
        self.assert_round_trip({})
        self.assert_round_trip({"gpu": 1, "note": "x: y"})
        self.assert_round_trip({"machine": ["test -f x", "python check.py"], "quality": [], "n": 1})

    def test_block_form_for_a_map_with_lists(self):
        text = serialize({"acceptance": {"machine": ["a b", "c"], "quality": []}})
        self.assertEqual(text, "acceptance:\n  machine: [a b, c]\n  quality: []\n")

    def test_flow_form_for_a_map_of_scalars(self):
        self.assertEqual(serialize({"r": {"gpu": 1, "cpu": 8}}), "r: {gpu: 1, cpu: 8}\n")

    def test_block_subkey_may_hold_a_flow_map(self):
        text = serialize({"a": {"b": {"c": 1}, "d": [1]}})
        self.assertEqual(text, "a:\n  b: {c: 1}\n  d: [1]\n")
        self.assertEqual(parse(text), {"a": {"b": {"c": 1}, "d": [1]}})

    def test_rejects_what_the_parser_cannot_read(self):
        with self.assertRaises(FrontmatterError):
            serialize({"a": {"b": {"c": {"d": 1}}}})
        with self.assertRaises(FrontmatterError):
            serialize({"a": {"b": [[1]]}})
        with self.assertRaises(FrontmatterError):
            serialize({"a": [[1]]})
        with self.assertRaises(FrontmatterError):
            serialize({"a": [{"k": 1}]})
        with self.assertRaises(FrontmatterError):
            serialize({"bad key": 1})
        with self.assertRaises(FrontmatterError):
            serialize({"a": float("inf")})
        with self.assertRaises(FrontmatterError) as caught:
            serialize({"a": object()})
        self.assertIsNone(caught.exception.line)
        self.assertNotIn("line", str(caught.exception).split(":")[0])

    def test_empty_mapping(self):
        self.assertEqual(serialize({}), "")
        self.assertEqual(parse(""), {})


class DocumentTest(unittest.TestCase):
    def test_body_is_kept_verbatim(self):
        text = "---\na: 1\n---\n\n## Demo\n\nText with --- inside\nand a: colon\n"
        mapping, body = load_document(text)
        self.assertEqual(mapping, {"a": 1})
        self.assertEqual(body, "\n## Demo\n\nText with --- inside\nand a: colon\n")
        self.assertEqual(dump_document(mapping, body), text)

    def test_brief_example_round_trips_after_one_normalizing_pass(self):
        original = brief_example_ticket()
        mapping, body = load_document(original)
        self.assertEqual(mapping["id"], 17)
        self.assertEqual(mapping["blocked_by"], [12, 14])
        self.assertIsNone(mapping["blocking"])
        self.assertIs(mapping["human_only"], False)
        self.assertEqual(mapping["resources"], {"gpu": 1, "cpu": 8, "ram_gb": 32, "wallclock_minutes": 90})
        self.assertEqual(mapping["acceptance"]["machine"][0], "python scripts/check_seeds.py results/ablation_b --min 3")
        self.assertEqual(mapping["goal_metric"], {"reports": "auroc_b", "expected_direction": "down"})
        self.assertEqual(mapping["demo"], "A table with three seeds showing the effect of removing the term on dataset B.")
        normalized = dump_document(mapping, body)
        again, body_again = load_document(normalized)
        self.assertEqual(again, mapping)
        self.assertEqual(body_again, body)
        self.assertEqual(dump_document(again, body_again), normalized)
        self.assertNotIn("#", normalized.split("---")[1].replace("SPEC.md#", "").replace("dossier.md#", "").replace("jsonl#", ""))

    def test_module_exports(self):
        for name in ["parse", "serialize", "load_document", "dump_document", "FrontmatterError"]:
            self.assertTrue(hasattr(frontmatter, name), name)


if __name__ == "__main__":
    unittest.main()
