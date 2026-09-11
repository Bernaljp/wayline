"""The in-house JSON Schema subset validator: one positive and one negative case per keyword."""

import unittest

from wayline import jsonschema
from wayline.jsonschema import SchemaError, ValidationError, check, check_schema, validate


def messages(instance, schema):
    return [(error.path, error.keyword) for error in validate(instance, schema)]


class TypeTest(unittest.TestCase):
    def test_each_type(self):
        cases = {
            "object": ({}, [1]), "array": ([], {}), "string": ("s", 1), "integer": (3, 3.5),
            "number": (3.5, "3.5"), "boolean": (True, 1), "null": (None, 0),
        }
        for name, (good, bad) in cases.items():
            with self.subTest(type=name):
                self.assertEqual(validate(good, {"type": name}), [])
                self.assertEqual(messages(bad, {"type": name}), [("$", "type")])

    def test_booleans_are_not_integers_or_numbers(self):
        self.assertEqual(messages(True, {"type": "integer"}), [("$", "type")])
        self.assertEqual(messages(False, {"type": "number"}), [("$", "type")])

    def test_integral_floats_are_integers(self):
        self.assertEqual(validate(2.0, {"type": "integer"}), [])

    def test_type_list(self):
        schema = {"type": ["integer", "null"]}
        self.assertEqual(validate(None, schema), [])
        self.assertEqual(validate(4, schema), [])
        self.assertEqual(messages("x", schema), [("$", "type")])


class ObjectKeywordsTest(unittest.TestCase):
    schema = {
        "type": "object",
        "required": ["id", "name"],
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "tags": {"type": "array"}},
        "additionalProperties": False,
    }

    def test_required(self):
        self.assertEqual(validate({"id": 1, "name": "a"}, self.schema), [])
        self.assertEqual(messages({"id": 1}, self.schema), [("$.name", "required")])

    def test_properties_report_the_nested_path(self):
        errors = validate({"id": "one", "name": "a"}, self.schema)
        self.assertEqual([(error.path, error.keyword) for error in errors], [("$.id", "type")])
        self.assertIn("expected integer", errors[0].message)

    def test_additional_properties_false(self):
        self.assertEqual(messages({"id": 1, "name": "a", "extra": 0}, self.schema), [("$.extra", "additionalProperties")])

    def test_additional_properties_schema(self):
        schema = {"type": "object", "additionalProperties": {"type": "string"}}
        self.assertEqual(validate({"a": "x"}, schema), [])
        self.assertEqual(messages({"a": 1}, schema), [("$.a", "type")])

    def test_object_keywords_ignore_non_objects(self):
        self.assertEqual(validate("text", {"required": ["x"], "properties": {"x": {"type": "integer"}}}), [])


class ArrayKeywordsTest(unittest.TestCase):
    schema = {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 3}

    def test_items(self):
        self.assertEqual(validate([1, 2], self.schema), [])
        self.assertEqual(messages([1, "two"], self.schema), [("$[1]", "type")])

    def test_min_and_max_items(self):
        self.assertEqual(messages([], self.schema), [("$", "minItems")])
        self.assertEqual(messages([1, 2, 3, 4], self.schema), [("$", "maxItems")])
        self.assertEqual(validate([1, 2, 3], self.schema), [])


class ValueKeywordsTest(unittest.TestCase):
    def test_enum(self):
        schema = {"enum": ["open", "done", 3, None]}
        for good in ["open", 3, None]:
            self.assertEqual(validate(good, schema), [])
        self.assertEqual(messages("closed", schema), [("$", "enum")])
        self.assertEqual(messages(True, {"enum": [1]}), [("$", "enum")])
        self.assertEqual(messages(1, {"enum": [True]}), [("$", "enum")])

    def test_const(self):
        self.assertEqual(validate("fixed", {"const": "fixed"}), [])
        self.assertEqual(messages("other", {"const": "fixed"}), [("$", "const")])
        self.assertEqual(validate({"a": [1, {"b": None}]}, {"const": {"a": [1, {"b": None}]}}), [])

    def test_minimum_and_maximum(self):
        schema = {"type": "number", "minimum": 0, "maximum": 1}
        for good in [0, 0.5, 1]:
            self.assertEqual(validate(good, schema), [])
        self.assertEqual(messages(-0.1, schema), [("$", "minimum")])
        self.assertEqual(messages(1.1, schema), [("$", "maximum")])

    def test_numeric_bounds_ignore_non_numbers(self):
        self.assertEqual(validate("x", {"minimum": 3}), [])
        self.assertEqual(validate(True, {"maximum": 0}), [])

    def test_pattern_is_unanchored_search(self):
        schema = {"type": "string", "pattern": "^t[0-9]+-a[0-9]+$"}
        self.assertEqual(validate("t17-a2", schema), [])
        self.assertEqual(messages("t17", schema), [("$", "pattern")])
        self.assertEqual(validate("abc", {"pattern": "b"}), [])
        self.assertEqual(validate(5, {"pattern": "b"}), [])

    def test_dollar_does_not_match_before_a_trailing_newline(self):
        self.assertEqual(messages("a" * 64 + "\n", {"pattern": "^[0-9a-f]{64}$"}), [("$", "pattern")])
        self.assertEqual(messages("worker\n", {"pattern": "^[a-z]+$"}), [("$", "pattern")])
        self.assertEqual(messages("b\n", {"pattern": "^a$|^b$"}), [("$", "pattern")])
        self.assertEqual(validate("b", {"pattern": "^a$|^b$"}), [])
        self.assertEqual(validate("x$y", {"pattern": "x[$]y"}), [])
        self.assertEqual(validate("x$", {"pattern": "x\\$"}), [])

    def test_nan_and_infinity_are_not_numbers(self):
        for value in [float("nan"), float("inf"), float("-inf")]:
            with self.subTest(value=value):
                self.assertEqual(messages(value, {"type": "number"}), [("$", "type")])
                self.assertEqual(messages(value, {"type": "integer"}), [("$", "type")])
                self.assertEqual(validate(value, {"minimum": 0}), [])  # not a number, so not compared


class CombinatorTest(unittest.TestCase):
    schema = {
        "oneOf": [
            {"type": "object", "required": ["kind"], "properties": {"kind": {"const": "a"}, "x": {"type": "integer"}}},
            {"type": "object", "required": ["kind"], "properties": {"kind": {"const": "b"}}},
        ]
    }

    def test_one_of_passes_with_exactly_one_match(self):
        self.assertEqual(validate({"kind": "a", "x": 1}, self.schema), [])
        self.assertEqual(validate({"kind": "b"}, self.schema), [])

    def test_one_of_fails_with_none(self):
        errors = validate({"kind": "c"}, self.schema)
        self.assertEqual([(error.path, error.keyword) for error in errors], [("$", "oneOf")])
        self.assertIn("none of the 2", errors[0].message)

    def test_one_of_fails_with_more_than_one(self):
        schema = {"oneOf": [{"type": "integer"}, {"type": "number"}]}
        self.assertEqual(messages(3, schema), [("$", "oneOf")])
        self.assertEqual(validate(3.5, schema), [])


class RefTest(unittest.TestCase):
    schema = {
        "type": "object",
        "properties": {"entry": {"$ref": "#/$defs/entry"}, "entries": {"type": "array", "items": {"$ref": "#/$defs/entry"}}},
        "$defs": {"entry": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}, "additionalProperties": False}},
    }

    def test_ref_within_the_same_file(self):
        self.assertEqual(validate({"entry": {"path": "a"}, "entries": [{"path": "b"}]}, self.schema), [])
        self.assertEqual(messages({"entries": [{"path": 1}]}, self.schema), [("$.entries[0].path", "type")])
        self.assertEqual(messages({"entry": {}}, self.schema), [("$.entry.path", "required")])

    def test_ref_to_definitions_and_root(self):
        schema = {"definitions": {"n": {"type": "integer"}}, "type": "object", "properties": {"a": {"$ref": "#/definitions/n"}}}
        self.assertEqual(messages({"a": "x"}, schema), [("$.a", "type")])
        recursive = {"type": "object", "properties": {"child": {"$ref": "#"}}, "additionalProperties": False}
        self.assertEqual(validate({"child": {"child": {}}}, recursive), [])
        self.assertEqual(messages({"child": {"child": {"bad": 1}}}, recursive), [("$.child.child.bad", "additionalProperties")])

    def test_ref_outside_the_file_is_rejected(self):
        with self.assertRaises(SchemaError):
            validate({}, {"$ref": "other.json#/x"})
        with self.assertRaises(SchemaError):
            validate({}, {"$ref": "#/$defs/missing"})

    def test_ref_must_point_at_a_schema(self):
        schema = {"title": "x", "type": "object", "properties": {"a": {"$ref": "#/title"}}}
        with self.assertRaises(SchemaError):
            check_schema(schema)
        with self.assertRaises(SchemaError):
            validate({"a": 5}, schema)

    def test_cyclic_refs_are_rejected(self):
        with self.assertRaises(SchemaError):
            check_schema({"$ref": "#"})
        with self.assertRaises(SchemaError):
            check_schema({"$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}})
        check_schema({"type": "object", "properties": {"child": {"$ref": "#"}}})  # consumes input: fine


class SchemaSubsetTest(unittest.TestCase):
    def test_keywords_outside_the_subset_are_rejected(self):
        for keyword, value in [("anyOf", []), ("allOf", []), ("minLength", 1), ("format", "date"),
                               ("patternProperties", {}), ("not", {}), ("if", {}), ("uniqueItems", True)]:
            with self.subTest(keyword=keyword):
                with self.assertRaises(SchemaError):
                    check_schema({"type": "string", keyword: value})

    def test_nested_schemas_are_checked(self):
        with self.assertRaises(SchemaError):
            check_schema({"type": "object", "properties": {"a": {"minLength": 2}}})
        with self.assertRaises(SchemaError):
            check_schema({"type": "array", "items": [{"type": "string"}]})
        with self.assertRaises(SchemaError):
            check_schema({"$defs": {"x": {"format": "uri"}}})
        with self.assertRaises(SchemaError):
            check_schema({"oneOf": [{"type": "string"}, {"anyOf": []}]})

    def test_bad_types_and_patterns_are_rejected(self):
        with self.assertRaises(SchemaError):
            check_schema({"type": "text"})
        with self.assertRaises(SchemaError):
            check_schema({"type": "string", "pattern": "("})
        with self.assertRaises(SchemaError):
            check_schema({"type": [["string"]]})

    def test_malformed_containers_are_rejected(self):
        for schema in [{"$defs": []}, {"properties": []}, {"definitions": "x"}, {"properties": {"a": "string"}}]:
            with self.subTest(schema=schema):
                with self.assertRaises(SchemaError):
                    check_schema(schema)

    def test_annotations_are_allowed(self):
        check_schema({"$schema": "x", "$id": "y", "title": "t", "description": "d", "default": 1,
                      "examples": [1], "$comment": "c", "type": "integer"})


class CheckTest(unittest.TestCase):
    def test_check_raises_with_every_error(self):
        schema = {"type": "object", "required": ["a", "b"], "additionalProperties": False}
        with self.assertRaises(ValidationError) as caught:
            check({"c": 1}, schema, name="thing")
        self.assertEqual(len(caught.exception.errors), 3)
        self.assertIn("thing", str(caught.exception))
        self.assertIn("$.a", str(caught.exception))

    def test_check_passes_silently(self):
        self.assertIsNone(check(1, {"type": "integer"}))

    def test_validation_error_survives_pickling(self):
        import pickle
        with self.assertRaises(ValidationError) as caught:
            check({"c": 1}, {"type": "object", "required": ["a"]}, name="thing")
        original = caught.exception
        again = pickle.loads(pickle.dumps(original))
        self.assertEqual(again.errors, original.errors)
        self.assertEqual(again.name, "thing")
        self.assertEqual(str(again), str(original))

    def test_load_schema_reads_and_caches(self):
        first = jsonschema.load_schema("journal_event")
        self.assertIs(first, jsonschema.load_schema("journal_event"))
        self.assertEqual(first["title"], "journal_event")
        with self.assertRaises(FileNotFoundError):
            jsonschema.load_schema("no_such_schema")


if __name__ == "__main__":
    unittest.main()
