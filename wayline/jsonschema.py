"""A JSON Schema validator for the subset the harness's schemas use (Implementation Decisions 2).

The standard library has no validator, and every structured value the harness trusts (a
worker's result, a ticket, a job file, the policy) is re-validated in code, so the subset is
small and exact: `type`, `required`, `properties`, `additionalProperties`, `enum`, `const`,
`items`, `minItems`, `maxItems`, `minimum`, `maximum`, `pattern`, `oneOf`, and `$ref` within
the same file. `check_schema` rejects any other keyword so a schema cannot silently promise a
check that is never run. Errors carry the failing path (`$.payload.ticket`, `$.entries[2]`).
"""

import json
import re
from collections import namedtuple

from wayline import SCHEMAS_DIR

__all__ = ["Error", "SchemaError", "ValidationError", "validate", "check", "check_schema", "load_schema"]

Error = namedtuple("Error", "path keyword message")

KEYWORDS = frozenset([
    "type", "required", "properties", "additionalProperties", "enum", "const", "items",
    "minItems", "maxItems", "minimum", "maximum", "pattern", "oneOf", "$ref",
])
ANNOTATIONS = frozenset(["$schema", "$id", "title", "description", "default", "examples", "$comment", "$defs", "definitions"])
TYPES = frozenset(["object", "array", "string", "integer", "number", "boolean", "null"])


class SchemaError(ValueError):
    """The schema itself is outside the subset or refers to something that does not exist."""


class ValidationError(ValueError):
    """An instance failed; `errors` holds every Error found."""

    def __init__(self, errors, name=None):
        self.errors = list(errors)
        self.name = name
        head = "%s is not valid" % (name or "instance")
        lines = ["  %s: %s" % (error.path, error.message) for error in self.errors]
        super().__init__("\n".join([head] + lines))


def validate(instance, schema, root=None):
    """Every Error in `instance` against `schema`; an empty list means valid."""
    errors = []
    _validate(instance, schema, schema if root is None else root, "$", errors)
    return errors


def check(instance, schema, root=None, name=None):
    """Raise ValidationError with every error, or return None when valid."""
    errors = validate(instance, schema, root)
    if errors:
        raise ValidationError(errors, name)
    return None


_cache = {}


def load_schema(name):
    """The shipped schema `schemas/<name>.json`, checked against the subset and cached."""
    if name not in _cache:
        path = SCHEMAS_DIR / (name + ".json")
        with open(path, encoding="utf-8") as handle:
            schema = json.load(handle)
        check_schema(schema)
        _cache[name] = schema
    return _cache[name]


# --- validation ------------------------------------------------------------------------------


def _validate(instance, schema, root, path, errors):
    if "$ref" in schema:
        _validate(instance, _resolve(schema["$ref"], root), root, path, errors)
    if "type" in schema and not _has_type(instance, schema["type"]):
        wanted = schema["type"] if isinstance(schema["type"], str) else " or ".join(schema["type"])
        errors.append(Error(path, "type", "expected %s, got %s" % (wanted, _type_name(instance))))
        return
    if "enum" in schema and not any(_equal(instance, option) for option in schema["enum"]):
        errors.append(Error(path, "enum", "%s is not one of %s" % (_show(instance), json.dumps(schema["enum"]))))
    if "const" in schema and not _equal(instance, schema["const"]):
        errors.append(Error(path, "const", "%s is not the constant %s" % (_show(instance), _show(schema["const"]))))
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(Error(_child(path, key), "required", "required property is missing"))
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                _validate(value, properties[key], root, _child(path, key), errors)
            elif "additionalProperties" in schema:
                extra = schema["additionalProperties"]
                if extra is False:
                    errors.append(Error(_child(path, key), "additionalProperties", "property is not allowed"))
                elif extra is not True:
                    _validate(value, extra, root, _child(path, key), errors)
    elif isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(Error(path, "minItems", "has %d items, fewer than minItems %d" % (len(instance), schema["minItems"])))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(Error(path, "maxItems", "has %d items, more than maxItems %d" % (len(instance), schema["maxItems"])))
        if "items" in schema:
            for index, item in enumerate(instance):
                _validate(item, schema["items"], root, "%s[%d]" % (path, index), errors)
    elif _is_number(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(Error(path, "minimum", "%s is less than minimum %s" % (instance, schema["minimum"])))
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(Error(path, "maximum", "%s is greater than maximum %s" % (instance, schema["maximum"])))
    elif isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(Error(path, "pattern", "%s does not match pattern %s" % (_show(instance), schema["pattern"])))
    if "oneOf" in schema:
        branches = schema["oneOf"]
        failures = []
        matches = 0
        for branch in branches:
            branch_errors = []
            _validate(instance, branch, root, path, branch_errors)
            if branch_errors:
                failures.append(branch_errors[0])
            else:
                matches += 1
        if matches != 1:
            if matches == 0:
                detail = "; ".join("(%d) %s: %s" % (index + 1, failure.path, failure.message) for index, failure in enumerate(failures))
                errors.append(Error(path, "oneOf", "matches none of the %d oneOf schemas: %s" % (len(branches), detail)))
            else:
                errors.append(Error(path, "oneOf", "matches %d of the %d oneOf schemas, not exactly one" % (matches, len(branches))))


def _child(path, key):
    return "%s.%s" % (path, key)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _has_type(instance, expected):
    names = [expected] if isinstance(expected, str) else expected
    for name in names:
        if name == "object" and isinstance(instance, dict):
            return True
        if name == "array" and isinstance(instance, list):
            return True
        if name == "string" and isinstance(instance, str):
            return True
        if name == "boolean" and isinstance(instance, bool):
            return True
        if name == "null" and instance is None:
            return True
        if name == "number" and _is_number(instance):
            return True
        if name == "integer" and _is_number(instance) and (isinstance(instance, int) or instance.is_integer()):
            return True
    return False


def _type_name(instance):
    if instance is None:
        return "null"
    if isinstance(instance, bool):
        return "boolean"
    if isinstance(instance, int):
        return "integer"
    if isinstance(instance, float):
        return "number"
    return {dict: "object", list: "array", str: "string"}.get(type(instance), type(instance).__name__)


def _equal(left, right):
    """JSON equality: booleans are not numbers, and 1 equals 1.0."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if _is_number(left) and _is_number(right):
        return left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    if type(left) is not type(right):
        return False
    return left == right


def _show(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 80 else text[:77] + "..."


def _resolve(ref, root):
    if not isinstance(ref, str) or not ref.startswith("#"):
        raise SchemaError("only a $ref within the same file is supported, got %r" % (ref,))
    node = root
    pointer = ref[1:]
    if pointer == "":
        return node
    if not pointer.startswith("/"):
        raise SchemaError("$ref %r is not a JSON pointer" % ref)
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            raise SchemaError("$ref %r does not resolve" % ref)
    return node


# --- the subset ------------------------------------------------------------------------------


def check_schema(schema, root=None, where="#"):
    """Raise SchemaError when `schema` uses anything outside the subset."""
    if root is None:
        root = schema
    if not isinstance(schema, dict):
        raise SchemaError("%s: a schema must be an object, got %s" % (where, _type_name(schema)))
    for keyword, value in schema.items():
        if keyword in ANNOTATIONS:
            if keyword in ("$defs", "definitions"):
                for name, definition in value.items():
                    check_schema(definition, root, "%s/%s/%s" % (where, keyword, name))
            continue
        if keyword not in KEYWORDS:
            raise SchemaError("%s: keyword %r is outside the validator's subset" % (where, keyword))
        if keyword == "type":
            names = [value] if isinstance(value, str) else value
            if not isinstance(names, list) or not names or any(name not in TYPES for name in names):
                raise SchemaError("%s: unknown type %r" % (where, value))
        elif keyword == "properties":
            for name, sub in value.items():
                check_schema(sub, root, "%s/properties/%s" % (where, name))
        elif keyword == "additionalProperties":
            if not isinstance(value, bool):
                check_schema(value, root, where + "/additionalProperties")
        elif keyword == "items":
            check_schema(value, root, where + "/items")
        elif keyword == "oneOf":
            if not isinstance(value, list) or not value:
                raise SchemaError("%s: oneOf must be a non-empty list" % where)
            for index, sub in enumerate(value):
                check_schema(sub, root, "%s/oneOf/%d" % (where, index))
        elif keyword == "required":
            if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
                raise SchemaError("%s: required must be a list of names" % where)
        elif keyword == "enum":
            if not isinstance(value, list) or not value:
                raise SchemaError("%s: enum must be a non-empty list" % where)
        elif keyword in ("minItems", "maxItems"):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SchemaError("%s: %s must be a non-negative integer" % (where, keyword))
        elif keyword in ("minimum", "maximum"):
            if not _is_number(value):
                raise SchemaError("%s: %s must be a number" % (where, keyword))
        elif keyword == "pattern":
            try:
                re.compile(value)
            except (re.error, TypeError) as failure:
                raise SchemaError("%s: pattern %r does not compile: %s" % (where, value, failure)) from None
        elif keyword == "$ref":
            _resolve(value, root)
