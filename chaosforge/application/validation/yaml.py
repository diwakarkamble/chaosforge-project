from typing import Any, ClassVar

from chaosforge.application.services.user_settings import is_supported_timezone


class YAMLValidationError:
    """Represents a single YAML validation error."""

    def __init__(
        self,
        path: str,
        message: str,
    ) -> None:
        self.path = path
        self.message = message

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class YAMLValidator:
    """
    Validates the structure of a ChaosForge campaign YAML.

    This validator only validates the YAML structure and basic types.
    Experiment-specific variables are validated separately by
    ExperimentValidationService.
    """

    ROOT_KEYS: ClassVar[set[str]] = {
        "campaign",
        "cloud",
        "environment",
        "settings",
        "experiments",
        "template",
    }

    CAMPAIGN_KEYS: ClassVar[set[str]] = {
        "name",
        "continue_on_failure",
        "irreversible_operations_acknowledged",
    }

    CLOUD_KEYS: ClassVar[set[str]] = {
        "provider",
    }

    ENVIRONMENT_KEYS: ClassVar[set[str]] = {
        "name",
        "account_id",
        "account_alias",
        "subscription_id",
        "subscription_name",
    }

    SETTINGS_KEYS: ClassVar[set[str]] = {"timezone"}

    EXPERIMENT_KEYS: ClassVar[set[str]] = {
        "service",
        "experiment",
        "variables",
    }

    SUPPORTED_PROVIDERS: ClassVar[set[str]] = {
        "aws",
        "azure",
    }

    def validate(
        self,
        data: Any,
    ) -> dict[str, Any]:
        """
        Validate a parsed YAML document.

        Returns:

            {
                "valid": True/False,
                "errors": [],
                "warnings": []
            }
        """

        errors: list[str] = []
        warnings: list[str] = []

        if not isinstance(data, dict):
            errors.append(
                "Root YAML document must be a mapping/object."
            )

            return self._result(
                errors,
                warnings,
            )

        self._validate_keys(
            data,
            self.ROOT_KEYS,
            "root",
            errors,
        )

        self._validate_campaign(
            data.get("campaign"),
            errors,
        )

        self._validate_cloud(
            data.get("cloud"),
            errors,
        )

        self._validate_experiments(
            data.get("experiments"),
            errors,
        )

        self._validate_settings(data.get("settings"), errors)

        if not errors:
            self._validate_environment(
                data.get("environment"),
                data.get("cloud", {}).get("provider") if isinstance(data.get("cloud"), dict) else None,
                data.get("template", False),
                errors,
            )

        return self._result(
            errors,
            warnings,
        )

    def _validate_environment(self, environment, provider, is_template, errors):
        if not isinstance(is_template, bool):
            errors.append("template: must be a boolean.")
            return
        if environment is None:
            if not is_template:
                errors.append("environment: is required for an executable campaign.")
            return
        if not isinstance(environment, dict):
            errors.append("environment: must be a mapping/object.")
            return
        self._validate_keys(environment, self.ENVIRONMENT_KEYS, "environment", errors)
        if is_template:
            return
        provider = str(provider or "").lower()
        identity_key = "account_id" if provider == "aws" else "subscription_id"
        identity = environment.get(identity_key)
        if not isinstance(identity, str) or not identity.strip():
            errors.append(
                f"environment.{identity_key}: is required for an executable {provider} campaign."
            )

    def _validate_settings(self, settings, errors):
        if settings is None:
            return
        if not isinstance(settings, dict):
            errors.append("settings: must be a mapping/object.")
            return
        self._validate_keys(settings, self.SETTINGS_KEYS, "settings", errors)
        timezone_id = settings.get("timezone")
        if timezone_id is not None and (
            not isinstance(timezone_id, str) or not is_supported_timezone(timezone_id)
        ):
            errors.append("settings.timezone: must be a supported IANA timezone.")

    def _validate_campaign(
        self,
        campaign: Any,
        errors: list[str],
    ) -> None:

        if campaign is None:
            return

        if not isinstance(campaign, dict):
            errors.append(
                "campaign: must be a mapping/object."
            )
            return

        self._validate_keys(
            campaign,
            self.CAMPAIGN_KEYS,
            "campaign",
            errors,
        )

        name = campaign.get("name")

        if name is not None and not isinstance(name, str):
            errors.append(
                "campaign.name: must be a string."
            )

        continue_on_failure = campaign.get(
            "continue_on_failure"
        )

        if (
            continue_on_failure is not None
            and not isinstance(continue_on_failure, bool)
        ):
            errors.append(
                "campaign.continue_on_failure: "
                "must be a boolean."
            )

        acknowledgement = campaign.get("irreversible_operations_acknowledged")
        if acknowledgement is not None and not isinstance(acknowledgement, bool):
            errors.append(
                "campaign.irreversible_operations_acknowledged: must be a boolean."
            )

    def _validate_cloud(
        self,
        cloud: Any,
        errors: list[str],
    ) -> None:

        if cloud is None:
            return

        if not isinstance(cloud, dict):
            errors.append(
                "cloud: must be a mapping/object."
            )
            return

        self._validate_keys(
            cloud,
            self.CLOUD_KEYS,
            "cloud",
            errors,
        )

        provider = cloud.get("provider")

        if provider is None:
            return

        if not isinstance(provider, str):
            errors.append(
                "cloud.provider: must be a string."
            )
            return

        if provider.lower() not in self.SUPPORTED_PROVIDERS:
            errors.append(
                "cloud.provider: unsupported provider "
                f"'{provider}'. Supported providers: "
                f"{', '.join(sorted(self.SUPPORTED_PROVIDERS))}."
            )

    def _validate_experiments(
        self,
        experiments: Any,
        errors: list[str],
    ) -> None:

        if experiments is None:
            errors.append(
                "experiments: is required."
            )
            return

        if not isinstance(experiments, list):
            errors.append(
                "experiments: must be a list."
            )
            return

        if not experiments:
            errors.append(
                "experiments: must contain at least one experiment."
            )
            return

        for index, experiment in enumerate(experiments):

            path = f"experiments[{index}]"

            if not isinstance(experiment, dict):
                errors.append(
                    f"{path}: must be a mapping/object."
                )
                continue

            self._validate_keys(
                experiment,
                self.EXPERIMENT_KEYS,
                path,
                errors,
            )

            service = experiment.get("service")

            if service is None:
                errors.append(
                    f"{path}.service: is required."
                )
            elif not isinstance(service, str):
                errors.append(
                    f"{path}.service: must be a string."
                )
            elif not service.strip():
                errors.append(
                    f"{path}.service: must not be empty."
                )

            experiment_id = experiment.get("experiment")

            if experiment_id is None:
                errors.append(
                    f"{path}.experiment: is required."
                )
            elif not isinstance(experiment_id, str):
                errors.append(
                    f"{path}.experiment: must be a string."
                )
            elif not experiment_id.strip():
                errors.append(
                    f"{path}.experiment: must not be empty."
                )

            variables = experiment.get("variables")

            if variables is None:
                errors.append(
                    f"{path}.variables: is required."
                )
            elif not isinstance(variables, dict):
                errors.append(
                    f"{path}.variables: must be a mapping/object."
                )

    @staticmethod
    def _validate_keys(
        data: dict[str, Any],
        allowed_keys: set[str],
        path: str,
        errors: list[str],
    ) -> None:

        for key in data:

            if key not in allowed_keys:
                errors.append(
                    f"{path}: unknown key '{key}'."
                )

    @staticmethod
    def _result(
        errors: list[str],
        warnings: list[str],
    ) -> dict[str, Any]:

        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
        }
