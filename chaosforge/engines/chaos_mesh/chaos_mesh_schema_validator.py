from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import yaml

from chaosforge.engines.chaos_mesh.chaos_mesh_installer import CHAOS_MESH_VERSION


@dataclass
class SchemaValidationError:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass
class ChaosMeshSchemaValidationResult:
    valid: bool
    kind: str
    errors: list[SchemaValidationError] = field(default_factory=list)

    @property
    def error_messages(self) -> list[str]:
        return [str(error) for error in self.errors]


class ChaosMeshCRDValidator:
    """
    Offline validator for Chaos Mesh Kubernetes CRDs.

    The validator reads the official Chaos Mesh CRD YAML files and
    validates generated manifests against their OpenAPI v3 schemas.

    Supported schema features:
      - type
      - required
      - properties
      - items
      - enum
      - anyOf
      - oneOf
      - allOf
      - additionalProperties
      - nullable
      - minItems
      - maxItems
      - minimum
      - maximum
      - pattern
      - x-kubernetes-preserve-unknown-fields
    """

    API_VERSION = "chaos-mesh.org/v1alpha1"

    KIND_TO_FILE: ClassVar[dict[str, str]] = {
        "PodChaos": "chaos-mesh.org_podchaos.yaml",
        "NetworkChaos": "chaos-mesh.org_networkchaos.yaml",
        "DNSChaos": "chaos-mesh.org_dnschaos.yaml",
        "HTTPChaos": "chaos-mesh.org_httpchaos.yaml",
        "StressChaos": "chaos-mesh.org_stresschaos.yaml",
        "IOChaos": "chaos-mesh.org_iochaos.yaml",
        "TimeChaos": "chaos-mesh.org_timechaos.yaml",
        "KernelChaos": "chaos-mesh.org_kernelchaos.yaml",
        "AWSChaos": "chaos-mesh.org_awschaos.yaml",
        "JVMChaos": "chaos-mesh.org_jvmchaos.yaml",
        "BlockChaos": "chaos-mesh.org_blockchaos.yaml",
        "PhysicalMachineChaos": (
            "chaos-mesh.org_physicalmachinechaos.yaml"
        ),
        "Schedule": "chaos-mesh.org_schedules.yaml",
        "StatusCheck": "chaos-mesh.org_statuschecks.yaml",
        "Workflow": "chaos-mesh.org_workflows.yaml",
    }

    def __init__(
        self,
        schema_dir: str | Path | None = None,
    ):
        self.schema_dir = (
            Path(schema_dir)
            if schema_dir is not None
            else Path(__file__).resolve().parent / "schemas" / f"v{CHAOS_MESH_VERSION}"
        )
        self._schemas: dict[str, dict[str, Any]] = {}

    def validate(
        self,
        manifest: dict[str, Any],
    ) -> ChaosMeshSchemaValidationResult:
        kind = manifest.get("kind")

        if not kind:
            return ChaosMeshSchemaValidationResult(
                valid=False,
                kind="",
                errors=[
                    SchemaValidationError(
                        path="$",
                        message="Manifest is missing 'kind'.",
                    )
                ],
            )

        if kind == "StatusCheck":
            return self._validate_status_check_as_workflow(
                manifest
            )

        schema = self._load_schema(kind)

        errors: list[SchemaValidationError] = []

        self._validate_value(
            value=manifest,
            schema=schema,
            path="$",
            errors=errors,
        )

        return ChaosMeshSchemaValidationResult(
            valid=not errors,
            kind=kind,
            errors=errors,
        )

    def _load_schema(
        self,
        kind: str,
    ) -> dict[str, Any]:
        if kind in self._schemas:
            return self._schemas[kind]

        filename = self.KIND_TO_FILE.get(kind)

        if not filename:
            raise ValueError(
                f"No Chaos Mesh CRD schema is registered for "
                f"kind '{kind}'."
            )

        path = self.schema_dir / filename

        if not path.exists():
            raise FileNotFoundError(
                f"Chaos Mesh CRD schema not found: {path}"
            )

        documents = list(
            yaml.safe_load_all(
                path.read_text(encoding="utf-8")
            )
        )

        crd = next(
            (
                document
                for document in documents
                if isinstance(document, dict)
                and document.get("kind")
                == "CustomResourceDefinition"
            ),
            None,
        )

        if not crd:
            raise ValueError(
                f"Invalid CRD file: {path}"
            )

        versions = (
            crd.get("spec", {})
            .get("versions", [])
        )

        version = next(
            (
                item
                for item in versions
                if item.get("name") == "v1alpha1"
            ),
            None,
        )

        if not version:
            raise ValueError(
                f"CRD '{kind}' has no v1alpha1 schema."
            )

        schema = (
            version
            .get("schema", {})
            .get("openAPIV3Schema")
        )

        if not isinstance(schema, dict):
            raise TypeError(
                f"CRD '{kind}' has no OpenAPI v3 schema."
            )

        self._schemas[kind] = schema

        return schema

    def _validate_value(
        self,
        value: Any,
        schema: dict[str, Any],
        path: str,
        errors: list[SchemaValidationError],
    ) -> None:
        if not isinstance(schema, dict):
            return

        if value is None:
            if schema.get("nullable") is True:
                return

            schema_type = schema.get("type")

            if schema_type:
                errors.append(
                    SchemaValidationError(
                        path,
                        "value must not be null",
                    )
                )

            return

        if schema.get(
            "x-kubernetes-preserve-unknown-fields"
        ):
            return

        if (
            "anyOf" in schema
            and not self._matches_any(
                value,
                schema["anyOf"],
            )
        ):
            errors.append(
                SchemaValidationError(
                    path,
                    "value does not match anyOf schemas",
                )
            )
            return

        if "oneOf" in schema:
            matches = self._matching_schema_count(
                value,
                schema["oneOf"],
            )

            if matches != 1:
                errors.append(
                    SchemaValidationError(
                        path,
                        f"value matches {matches} oneOf schemas; "
                        "expected exactly one",
                    )
                )
                return

        if "allOf" in schema:
            for index, child in enumerate(
                schema["allOf"]
            ):
                self._validate_value(
                    value,
                    child,
                    path,
                    errors,
                )

        expected_type = schema.get("type")

        if expected_type and not self._type_matches(
            value,
            expected_type,
        ):
            errors.append(
                SchemaValidationError(
                    path,
                    f"expected type '{expected_type}', "
                    f"got '{self._python_type(value)}'",
                )
            )
            return

        enum = schema.get("enum")

        if enum is not None and value not in enum:
            errors.append(
                SchemaValidationError(
                    path,
                    f"value {value!r} is not one of "
                    f"{enum!r}",
                )
            )

        if isinstance(value, dict):
            self._validate_object(
                value,
                schema,
                path,
                errors,
            )

        elif isinstance(value, list):
            self._validate_array(
                value,
                schema,
                path,
                errors,
            )

        elif isinstance(value, str):
            self._validate_string(
                value,
                schema,
                path,
                errors,
            )

        elif isinstance(value, (int, float)) and not isinstance(
            value,
            bool,
        ):
            self._validate_number(
                value,
                schema,
                path,
                errors,
            )

    def _validate_object(
        self,
        value: dict[str, Any],
        schema: dict[str, Any],
        path: str,
        errors: list[SchemaValidationError],
    ) -> None:
        properties = schema.get(
            "properties",
            {},
        )

        if not isinstance(properties, dict):
            properties = {}

        required = schema.get(
            "required",
            [],
        )

        for field_name in required:
            if field_name not in value:
                errors.append(
                    SchemaValidationError(
                        f"{path}.{field_name}",
                        "required property is missing",
                    )
                )

        for field_name, field_value in value.items():
            child_path = (
                f"{path}.{field_name}"
            )

            child_schema = properties.get(
                field_name
            )

            if child_schema is not None:
                self._validate_value(
                    field_value,
                    schema=child_schema,
                    path=child_path,
                    errors=errors,
                )
                continue

            additional = schema.get(
                "additionalProperties"
            )

            if additional is False:
                errors.append(
                    SchemaValidationError(
                        child_path,
                        "unknown property",
                    )
                )
            elif isinstance(additional, dict):
                self._validate_value(
                    field_value,
                    additional,
                    child_path,
                    errors,
                )

    def _validate_array(
        self,
        value: list[Any],
        schema: dict[str, Any],
        path: str,
        errors: list[SchemaValidationError],
    ) -> None:
        min_items = schema.get("minItems")

        if (
            isinstance(min_items, int)
            and len(value) < min_items
        ):
            errors.append(
                SchemaValidationError(
                    path,
                    f"must contain at least {min_items} items",
                )
            )

        max_items = schema.get("maxItems")

        if (
            isinstance(max_items, int)
            and len(value) > max_items
        ):
            errors.append(
                SchemaValidationError(
                    path,
                    f"must contain at most {max_items} items",
                )
            )

        item_schema = schema.get("items")

        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                self._validate_value(
                    item,
                    item_schema,
                    f"{path}[{index}]",
                    errors,
                )

    def _validate_string(
        self,
        value: str,
        schema: dict[str, Any],
        path: str,
        errors: list[SchemaValidationError],
    ) -> None:
        min_length = schema.get("minLength")

        if (
            isinstance(min_length, int)
            and len(value) < min_length
        ):
            errors.append(
                SchemaValidationError(
                    path,
                    f"must contain at least "
                    f"{min_length} characters",
                )
            )

        max_length = schema.get("maxLength")

        if (
            isinstance(max_length, int)
            and len(value) > max_length
        ):
            errors.append(
                SchemaValidationError(
                    path,
                    f"must contain at most "
                    f"{max_length} characters",
                )
            )

        pattern = schema.get("pattern")

        if pattern:
            import re

            try:
                matched = re.search(
                    pattern,
                    value,
                )
            except re.error:
                matched = True

            if not matched:
                errors.append(
                    SchemaValidationError(
                        path,
                        f"value does not match pattern "
                        f"'{pattern}'",
                    )
                )

    def _validate_number(
        self,
        value: float,
        schema: dict[str, Any],
        path: str,
        errors: list[SchemaValidationError],
    ) -> None:
        minimum = schema.get("minimum")

        if (
            minimum is not None
            and value < minimum
        ):
            errors.append(
                SchemaValidationError(
                    path,
                    f"value must be >= {minimum}",
                )
            )

        maximum = schema.get("maximum")

        if (
            maximum is not None
            and value > maximum
        ):
            errors.append(
                SchemaValidationError(
                    path,
                    f"value must be <= {maximum}",
                )
            )

    def _validate_status_check_as_workflow(
        self,
        manifest: dict[str, Any],
    ) -> ChaosMeshSchemaValidationResult:
        """
        StatusCheck is represented by Chaos Mesh as a workflow
        template in the current Chaos Mesh integration.

        Validate the generated object against Workflow rather
        than pretending StatusCheck is an independent resource.
        """
        workflow_schema = self._load_schema("Workflow")

        errors: list[SchemaValidationError] = []

        self._validate_value(
            manifest,
            workflow_schema,
            "$",
            errors,
        )

        return ChaosMeshSchemaValidationResult(
            valid=not errors,
            kind="StatusCheck",
            errors=errors,
        )

    def _matches_any(
        self,
        value: Any,
        schemas: list[dict[str, Any]],
    ) -> bool:
        return any(
            self._schema_matches(value, schema)
            for schema in schemas
        )

    def _matching_schema_count(
        self,
        value: Any,
        schemas: list[dict[str, Any]],
    ) -> int:
        return sum(
            1
            for schema in schemas
            if self._schema_matches(value, schema)
        )

    def _schema_matches(
        self,
        value: Any,
        schema: dict[str, Any],
    ) -> bool:
        errors: list[SchemaValidationError] = []

        self._validate_value(
            value,
            schema,
            "$",
            errors,
        )

        return not errors

    @staticmethod
    def _type_matches(
        value: Any,
        expected: str,
    ) -> bool:
        if expected == "object":
            return isinstance(value, dict)

        if expected == "array":
            return isinstance(value, list)

        if expected == "string":
            return isinstance(value, str)

        if expected == "boolean":
            return isinstance(value, bool)

        if expected == "integer":
            return (
                isinstance(value, int)
                and not isinstance(value, bool)
            )

        if expected == "number":
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
            )

        return True

    @staticmethod
    def _python_type(value: Any) -> str:
        if isinstance(value, bool):
            return "boolean"

        if isinstance(value, int):
            return "integer"

        if isinstance(value, float):
            return "number"

        if isinstance(value, str):
            return "string"

        if isinstance(value, list):
            return "array"

        if isinstance(value, dict):
            return "object"

        if value is None:
            return "null"

        return type(value).__name__
