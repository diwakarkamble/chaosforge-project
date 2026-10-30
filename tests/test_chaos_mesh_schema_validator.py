import json
from pathlib import Path
from types import SimpleNamespace

from chaosforge.engines.chaos_mesh.chaos_mesh_experiment_mapper import (
    ChaosMeshExperimentMapper,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_schema_validator import (
    ChaosMeshCRDValidator,
)

CATALOG_DIR = (
    Path(__file__).resolve().parents[1]
    / "chaosforge"
    / "engines"
    / "chaos_mesh"
    / "experiments"
)


def test_all_chaos_mesh_catalog_manifests_match_v287_crds():
    metadata = json.loads(
        (CATALOG_DIR / "metadata.json").read_text(
            encoding="utf-8"
        )
    )

    experiments = metadata["experiments"]

    assert len(experiments) == 31

    mapper = ChaosMeshExperimentMapper()
    validator = ChaosMeshCRDValidator()

    failures = []

    for item in experiments:
        experiment_id = item["id"]
        json_path = CATALOG_DIR / "definitions" / item["json"]

        variables = {}

        # Catalog placeholders required only to construct
        # an otherwise valid manifest offline.
        if experiment_id == "chaos-mesh-aws":
            variables["ec2_instance"] = (
                "i-00000000000000000"
            )

        if experiment_id == "chaos-mesh-physical-machine":
            variables["physical_machine"] = "physical-machine-a"

        experiment = SimpleNamespace(
            id=experiment_id,
            name=item["name"],
            service="chaos_mesh",
            json_file=str(json_path),
            variables=variables,
        )

        try:
            manifest = mapper.build_manifest(experiment)
            result = validator.validate(manifest)

            if not result.valid:
                failures.append(
                    f"{experiment_id} "
                    f"({manifest.get('kind')}):\n"
                    + "\n".join(
                        f"  - {error}"
                        for error in result.errors
                    )
                )

        except Exception as exc:  # noqa: BLE001
            failures.append(
                f"{experiment_id}: "
                f"{type(exc).__name__}: {exc}"
            )

    assert not failures, (
        "Chaos Mesh v2.8.7 schema validation failures:\n"
        + "\n".join(failures)
    )


def test_validate_missing_kind():
    validator = ChaosMeshCRDValidator()

    result = validator.validate({})

    assert result.valid is False
    assert result.kind == ""
    assert result.error_messages == [
        "$: Manifest is missing 'kind'."
    ]


def test_load_schema_unknown_kind():
    validator = ChaosMeshCRDValidator()

    try:
        validator._load_schema("UnknownChaos")
    except ValueError as exc:
        assert "No Chaos Mesh CRD schema is registered" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_load_schema_missing_file(tmp_path):
    validator = ChaosMeshCRDValidator(schema_dir=tmp_path)

    try:
        validator._load_schema("PodChaos")
    except FileNotFoundError as exc:
        assert "Chaos Mesh CRD schema not found" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError")


def test_load_schema_invalid_crd(tmp_path):
    schema_file = tmp_path / "chaos-mesh.org_podchaos.yaml"
    schema_file.write_text(
        """
apiVersion: apiextensions.k8s.io/v1
kind: NotACRD
metadata:
  name: test
""",
        encoding="utf-8",
    )

    validator = ChaosMeshCRDValidator(schema_dir=tmp_path)

    try:
        validator._load_schema("PodChaos")
    except ValueError as exc:
        assert "Invalid CRD file" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_load_schema_missing_v1alpha1(tmp_path):
    schema_file = tmp_path / "chaos-mesh.org_podchaos.yaml"
    schema_file.write_text(
        """
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: podchaos.chaos-mesh.org
spec:
  versions:
    - name: v1beta1
      schema:
        openAPIV3Schema:
          type: object
""",
        encoding="utf-8",
    )

    validator = ChaosMeshCRDValidator(schema_dir=tmp_path)

    try:
        validator._load_schema("PodChaos")
    except ValueError as exc:
        assert "has no v1alpha1 schema" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_load_schema_missing_openapi_schema(tmp_path):
    schema_file = tmp_path / "chaos-mesh.org_podchaos.yaml"
    schema_file.write_text(
        """
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: podchaos.chaos-mesh.org
spec:
  versions:
    - name: v1alpha1
      schema: {}
""",
        encoding="utf-8",
    )

    validator = ChaosMeshCRDValidator(schema_dir=tmp_path)

    try:
        validator._load_schema("PodChaos")
    except TypeError as exc:
        assert "has no OpenAPI v3 schema" in str(exc)
    else:
        raise AssertionError("Expected TypeError")


def test_load_schema_uses_cache(tmp_path):
    schema_file = tmp_path / "chaos-mesh.org_podchaos.yaml"
    schema_file.write_text(
        """
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: podchaos.chaos-mesh.org
spec:
  versions:
    - name: v1alpha1
      schema:
        openAPIV3Schema:
          type: object
""",
        encoding="utf-8",
    )

    validator = ChaosMeshCRDValidator(schema_dir=tmp_path)

    first = validator._load_schema("PodChaos")
    second = validator._load_schema("PodChaos")

    assert first is second


def test_validate_nullable_and_null():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        None,
        {"type": "string", "nullable": True},
        "$.value",
        errors,
    )

    assert errors == []

    validator._validate_value(
        None,
        {"type": "string"},
        "$.value",
        errors,
    )

    assert len(errors) == 1
    assert errors[0].message == "value must not be null"


def test_validate_preserve_unknown_fields():
    validator = ChaosMeshCRDValidator()
    errors = []

    validator._validate_value(
        {"anything": "allowed"},
        {
            "type": "object",
            "x-kubernetes-preserve-unknown-fields": True,
        },
        "$",
        errors,
    )

    assert errors == []


def test_validate_any_of():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        "hello",
        {
            "anyOf": [
                {"type": "integer"},
                {"type": "string"},
            ]
        },
        "$",
        errors,
    )

    assert errors == []

    errors = []

    validator._validate_value(
        [],
        {
            "anyOf": [
                {"type": "integer"},
                {"type": "string"},
            ]
        },
        "$",
        errors,
    )

    assert len(errors) == 1
    assert "anyOf" in errors[0].message


def test_validate_one_of():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        10,
        {
            "oneOf": [
                {"type": "integer"},
                {"type": "number"},
            ]
        },
        "$",
        errors,
    )

    assert len(errors) == 1
    assert "oneOf" in errors[0].message


def test_validate_all_of():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        10,
        {
            "allOf": [
                {"type": "integer"},
                {"minimum": 5},
            ]
        },
        "$",
        errors,
    )

    assert errors == []


def test_validate_wrong_type():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        "not-an-integer",
        {"type": "integer"},
        "$.value",
        errors,
    )

    assert len(errors) == 1
    assert "expected type 'integer'" in errors[0].message


def test_validate_enum():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        "invalid",
        {
            "type": "string",
            "enum": ["one", "two"],
        },
        "$.value",
        errors,
    )

    assert len(errors) == 1
    assert "is not one of" in errors[0].message


def test_validate_object_required_and_unknown_properties():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        {"unknown": "value"},
        {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "$",
        errors,
    )

    messages = [error.message for error in errors]

    assert "required property is missing" in messages
    assert "unknown property" in messages


def test_validate_additional_properties_schema():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        {"count": "wrong"},
        {
            "type": "object",
            "additionalProperties": {
                "type": "integer",
            },
        },
        "$",
        errors,
    )

    assert len(errors) == 1
    assert "$.count" in errors[0].path


def test_validate_array_limits_and_items():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        [],
        {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {"type": "string"},
        },
        "$.items",
        errors,
    )

    assert any("at least 1" in error.message for error in errors)

    errors = []

    validator._validate_value(
        ["a", "b", "c"],
        {
            "type": "array",
            "maxItems": 2,
            "items": {"type": "string"},
        },
        "$.items",
        errors,
    )

    assert any("at most 2" in error.message for error in errors)


def test_validate_string_constraints():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        "a",
        {
            "type": "string",
            "minLength": 3,
            "maxLength": 5,
        },
        "$.value",
        errors,
    )

    assert any("at least 3" in error.message for error in errors)

    errors = []

    validator._validate_value(
        "abcdef",
        {
            "type": "string",
            "maxLength": 5,
        },
        "$.value",
        errors,
    )

    assert any("at most 5" in error.message for error in errors)


def test_validate_pattern():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        "abc",
        {
            "type": "string",
            "pattern": "^\\d+$",
        },
        "$.value",
        errors,
    )

    assert len(errors) == 1
    assert "does not match pattern" in errors[0].message


def test_validate_invalid_pattern_is_tolerated():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        "abc",
        {
            "type": "string",
            "pattern": "[",
        },
        "$.value",
        errors,
    )

    assert errors == []


def test_validate_number_constraints():
    validator = ChaosMeshCRDValidator()

    errors = []

    validator._validate_value(
        2,
        {
            "type": "number",
            "minimum": 5,
            "maximum": 10,
        },
        "$.value",
        errors,
    )

    assert any("must be >= 5" in error.message for error in errors)

    errors = []

    validator._validate_value(
        20,
        {
            "type": "number",
            "minimum": 5,
            "maximum": 10,
        },
        "$.value",
        errors,
    )

    assert any("must be <= 10" in error.message for error in errors)

def test_type_matches():
    assert ChaosMeshCRDValidator._type_matches({}, "object")
    assert ChaosMeshCRDValidator._type_matches([], "array")
    assert ChaosMeshCRDValidator._type_matches("x", "string")
    assert ChaosMeshCRDValidator._type_matches(True, "boolean")
    assert ChaosMeshCRDValidator._type_matches(1, "integer")
    assert ChaosMeshCRDValidator._type_matches(1.5, "number")

    assert not ChaosMeshCRDValidator._type_matches(True, "integer")
    assert not ChaosMeshCRDValidator._type_matches(True, "number")

    # Unknown schema types are treated as unconstrained.
    assert ChaosMeshCRDValidator._type_matches("x", "unknown")


def test_python_type():
    assert ChaosMeshCRDValidator._python_type(True) == "boolean"
    assert ChaosMeshCRDValidator._python_type(1) == "integer"
    assert ChaosMeshCRDValidator._python_type(1.5) == "number"
    assert ChaosMeshCRDValidator._python_type("x") == "string"
    assert ChaosMeshCRDValidator._python_type([]) == "array"
    assert ChaosMeshCRDValidator._python_type({}) == "object"
    assert ChaosMeshCRDValidator._python_type(None) == "null"
    assert ChaosMeshCRDValidator._python_type(object()) == "object"


def test_status_check_is_validated_as_workflow():
    validator = ChaosMeshCRDValidator()

    manifest = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "StatusCheck",
        "metadata": {
            "name": "status-check-test",
            "namespace": "default",
        },
        "spec": {
            "entry": "status-check",
            "templates": [
                {
                    "name": "status-check",
                    "templateType": "StatusCheck",
                    "statusCheck": {
                        "mode": "Synchronous",
                        "type": "HTTP",
                        "http": {
                            "url": "http://example.com",
                            "method": "GET",
                            "criteria": {
                                "statusCode": "200",
                            },
                        },
                    },
                    "abortWithStatusCheck": False,
                }
            ],
        },
    }

    result = validator.validate(manifest)

    assert result.kind == "StatusCheck"
    assert result.valid is True
    assert result.errors == []

def test_validate_any_of_failure():
    validator = ChaosMeshCRDValidator()
    errors = []

    validator._validate_value(
        [],
        {
            "anyOf": [
                {"type": "integer"},
                {"type": "string"},
            ],
        },
        "$",
        errors,
    )

    assert len(errors) == 1
    assert errors[0].message == "value does not match anyOf schemas"


def test_validate_one_of_requires_exactly_one_match():
    validator = ChaosMeshCRDValidator()
    errors = []

    validator._validate_value(
        10,
        {
            "oneOf": [
                {"type": "integer"},
                {"type": "number"},
            ],
        },
        "$",
        errors,
    )

    assert len(errors) == 1
    assert "oneOf schemas" in errors[0].message




def test_validate_type_mismatch():
    validator = ChaosMeshCRDValidator()
    errors = []

    validator._validate_value(
        "10",
        {"type": "integer"},
        "$.value",
        errors,
    )

    assert len(errors) == 1
    assert "expected type 'integer'" in errors[0].message


def test_validate_enum_failure():
    validator = ChaosMeshCRDValidator()
    errors = []

    validator._validate_value(
        "invalid",
        {
            "type": "string",
            "enum": ["one", "two"],
        },
        "$.value",
        errors,
    )

    assert len(errors) == 1
    assert "is not one of" in errors[0].message


def test_type_matches_all_supported_types():
    validator = ChaosMeshCRDValidator

    assert validator._type_matches({}, "object")
    assert validator._type_matches([], "array")
    assert validator._type_matches("value", "string")
    assert validator._type_matches(True, "boolean")
    assert validator._type_matches(10, "integer")
    assert validator._type_matches(10.5, "number")

    assert not validator._type_matches(True, "integer")
    assert not validator._type_matches(True, "number")

    # Unknown schema types are treated as unconstrained.
    assert validator._type_matches("value", "unknown")


def test_python_type_all_supported_types():
    validator = ChaosMeshCRDValidator

    assert validator._python_type(True) == "boolean"
    assert validator._python_type(10) == "integer"
    assert validator._python_type(10.5) == "number"
    assert validator._python_type("value") == "string"
    assert validator._python_type([]) == "array"
    assert validator._python_type({}) == "object"
    assert validator._python_type(None) == "null"
    assert validator._python_type(object()) == "object"

def test_validate_value_ignores_non_dict_schema():
    validator = ChaosMeshCRDValidator()
    errors = []

    validator._validate_value(
        "value",
        "invalid-schema",
        "$",
        errors,
    )

    assert errors == []


def test_validate_object_handles_non_dict_properties():
    validator = ChaosMeshCRDValidator()
    errors = []

    validator._validate_object(
        {"field": "value"},
        {"properties": "invalid-properties"},
        "$",
        errors,
    )

    assert errors == []
