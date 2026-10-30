from __future__ import annotations

import json
import os
from typing import Any

from chaosforge.application.duration import duration_seconds, is_iso8601_duration
from chaosforge.engines.chaos_mesh.chaos_mesh_manifest_builder import (
    ChaosMeshManifestBuilder,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_target_resolver import (
    ChaosMeshTargetResolver,
)


class ChaosMeshExperimentMapper:
    """
    Converts a ChaosForge Chaos Mesh experiment definition into
    an executable Chaos Mesh Kubernetes manifest.
    """

    REQUIRED_MANIFEST_FIELDS = (
        "apiVersion",
        "kind",
        "metadata",
        "spec",
    )

    def __init__(
        self,
        builder: ChaosMeshManifestBuilder | None = None,
        target_resolver: ChaosMeshTargetResolver | None = None,
    ):
        self.builder = builder or ChaosMeshManifestBuilder()
        self.target_resolver = target_resolver

    def build_manifest(self, experiment: Any) -> dict[str, Any]:

        variables = getattr(
            experiment,
            "variables",
            {},
        ) or {}
        if is_iso8601_duration(variables.get("duration", "")):
            variables = {**variables, "duration": f"{duration_seconds(variables['duration'])}s"}

        #
        # Preserve direct-manifest compatibility.
        #
        direct_manifest = variables.get("manifest")

        if isinstance(direct_manifest, dict):
            return self._validate_manifest(
                direct_manifest
            )

        json_file = getattr(
            experiment,
            "json_file",
            None,
        )

        if not json_file:
            raise ValueError(
                "Chaos Mesh experiment requires "
                "variables['manifest'] or json_file."
            )

        definition = self._load_definition(
            json_file
        )

        chaos_mesh = definition.get(
            "chaos_mesh",
            {},
        )

        if not isinstance(chaos_mesh, dict):
            raise TypeError(
                "Chaos Mesh experiment definition must contain "
                "a 'chaos_mesh' object."
            )

        kind = chaos_mesh.get("kind")
        action = chaos_mesh.get("action")

        if not kind:
            raise ValueError(
                "Chaos Mesh experiment definition is missing "
                "'chaos_mesh.kind'."
            )

        if (
            not action
            and kind not in {
                "Workflow",
                "Schedule",
                "StatusCheck",
            }
        ):
            raise ValueError(
                "Chaos Mesh experiment definition is missing "
                "'chaos_mesh.action'."
            )

        configuration = definition.get(
            "configuration",
            {},
        )

        if not isinstance(configuration, dict):
            raise TypeError(
                "Chaos Mesh experiment 'configuration' "
                "must be an object."
            )

        #
        # Runtime variables override catalog defaults.
        #
        config = dict(configuration)

        for key, value in variables.items():
            if key != "manifest":
                config[key] = value

        namespace = str(
            config.pop(
                "namespace",
                "default",
            )
        )

        #
        # Resolve EKS target when requested.
        #
        cluster = config.pop(
            "eks_cluster",
            None,
        )

        if cluster is None:
            cluster = config.pop(
                "cluster",
                None,
            )

        pod = config.pop(
            "pod",
            None,
        )

        deployment = config.pop(
            "deployment",
            None,
        )

        node = config.pop(
            "node",
            None,
        )

        labels = config.pop(
            "labels",
            None,
        )

        if config.get("time_offset") and not config.get("offset"):
            config["offset"] = config["time_offset"]
        config.pop("time_offset", None)
        if config.get("dns_pattern") and not config.get("patterns"):
            config["patterns"] = [config["dns_pattern"]]
        config.pop("dns_pattern", None)
        if config.get("http_port") and not config.get("port"):
            config["port"] = config["http_port"]
        config.pop("http_port", None)
        if config.get("http_delay") and not config.get("delay"):
            config["delay"] = config["http_delay"]
        config.pop("http_delay", None)
        if config.get("io_percent") and not config.get("percent"):
            config["percent"] = config["io_percent"]
        config.pop("io_percent", None)
        if config.get("io_errno") and not config.get("errno"):
            config["errno"] = config["io_errno"]
        config.pop("io_errno", None)
        if config.get("container_name") and not config.get("container_names"):
            config["container_names"] = [config["container_name"]]
        config.pop("container_name", None)
        if config.get("chaos_value") and not config.get("value"):
            config["value"] = config["chaos_value"]
        config.pop("chaos_value", None)
        # Execution controls are consumed by ChaosMeshRunner, never CRD specs.
        for key in {
            "dry_run",
            "wait_for_completion",
            "cleanup_after_execution",
            "timeout_seconds",
            "poll_interval_seconds",
            # Captured only by the separate EKS replica-reduction workflow.
            "original_replicas",
        }:
            config.pop(key, None)

        if deployment and not labels and self.target_resolver is not None:
            labels = self.target_resolver.deployment_selector(
                cluster, namespace, deployment
            )

        if (
            self.target_resolver is not None
            and cluster
        ):
            self._validate_target(
                cluster=cluster,
                namespace=namespace,
                pod=pod,
                deployment=deployment,
                node=node,
            )

        #
        # Convert convenient ChaosForge target fields into
        # Chaos Mesh selector syntax.
        #
        selector = config.get("selector")

        selector_kinds = {
            "PodChaos",
            "NetworkChaos",
            "DNSChaos",
            "HTTPChaos",
            "IOChaos",
            "StressChaos",
            "TimeChaos",
            "KernelChaos",
            "JVMChaos",
            "BlockChaos",
            "PhysicalMachineChaos",
        }

        if kind in selector_kinds and not selector:
            if pod or labels:
                selector = (
                    self.target_resolver.pod_selector(
                        namespace=namespace,
                        pod=pod,
                        labels=labels,
                    )
                    if self.target_resolver is not None
                    else self._pod_selector(
                        namespace=namespace,
                        pod=pod,
                        labels=labels,
                    )
                )
            elif namespace:
                selector = (
                    self.target_resolver.pod_selector(
                        namespace=namespace,
                    )
                    if self.target_resolver is not None
                    else self._pod_selector(
                        namespace=namespace,
                    )
                )

        if selector and kind in selector_kinds:
            config["selector"] = selector

        #
        # Node target.
        #
        if node and kind in selector_kinds:
            config["selector"] = (
                self.target_resolver.node_selector()
                if self.target_resolver is not None
                else {}
            )

            config["selector"].setdefault(
                "nodes",
                [node],
            )

        name = self._resource_name(
            experiment,
            kind,
            action,
        )

        if isinstance(config.get("duration"), int):
            config["duration"] = f"{config['duration']}s"

        builder_method = getattr(
            self.builder,
            f"build_{self._kind_to_method(kind)}",
            None,
        )

        if builder_method is None:
            raise ValueError(
                f"No Chaos Mesh builder is available "
                f"for kind '{kind}'."
            )

        #
        # Normalize ChaosForge catalog configuration into the
        # exact argument shape expected by each builder.
        #
        if kind != "AWSChaos":
            config.pop("aws_region", None)
            # create_experiment preserves this legacy alias for Chaos Toolkit
            # definitions, but Chaos Mesh builders do not accept it.
            config.pop("region", None)

        if kind == "StressChaos":
            config.pop("action", None)

            stressors = config.pop(
                "stressors",
                {},
            )

            normalized_stressors = {}

            cpu = stressors.get("cpu")

            if isinstance(cpu, int):
                normalized_stressors["cpu"] = {
                    "workers": cpu,
                    "load": 100,
                }
            elif isinstance(cpu, dict):
                normalized_stressors["cpu"] = dict(cpu)

            memory = stressors.get("memory")

            if isinstance(memory, int):
                normalized_stressors["memory"] = {
                    "workers": 1,
                    "size": f"{memory}MB",
                }
            elif isinstance(memory, dict):
                normalized_stressors["memory"] = dict(memory)

            for key, value in stressors.items():
                if key not in {"cpu", "memory"}:
                    normalized_stressors[key] = value

            return builder_method(
                name=name,
                namespace=namespace,
                mode=config.pop("mode", "one"),
                stressors=normalized_stressors,
                selector=config.pop("selector", None),
                duration=config.pop("duration", None),
                value=config.pop("value", None),
            )

        if kind == "HTTPChaos":
            config.pop("action", None)

            patch = config.get("patch")

            if isinstance(patch, dict):
                patch = dict(patch)

                headers = patch.get("headers")

                if isinstance(headers, dict):
                    patch["headers"] = [
                        [key, value]
                        for key, value in headers.items()
                    ]

                queries = patch.get("queries")

                if isinstance(queries, dict):
                    patch["queries"] = [
                        [key, value]
                        for key, value in queries.items()
                    ]

                config["patch"] = patch

            return builder_method(
                name=name,
                namespace=namespace,
                mode=config.pop("mode", "one"),
                selector=config.pop("selector", None),
                target=config.pop("target", "Request"),
                port=config.pop("port", None),
                method=config.pop("method", None),
                path=config.pop("path", None),
                duration=config.pop("duration", None),
                abort=config.pop("abort", None),
                delay=config.pop("delay", None),
                replace=config.pop("replace", None),
                patch=config.pop("patch", None),
                request_headers=config.pop(
                    "request_headers",
                    None,
                ),
            )

        if kind == "IOChaos":
            config.pop("action", None)

            # ChaosForge catalog uses the convenient "latency"
            # name; Chaos Mesh builder expects "delay".
            if "latency" in config and "delay" not in config:
                config["delay"] = config.pop("latency")

            # ChaosForge uses attr_override; builder expects attr.
            if "attr_override" in config and "attr" not in config:
                config["attr"] = config.pop("attr_override")

            attr = config.get("attr")

            if isinstance(attr, dict):
                attr = dict(attr)

                if isinstance(attr.get("perm"), str):
                    permission = attr["perm"]

                    try:
                        attr["perm"] = int(
                            permission,
                            8,
                        )
                    except ValueError:
                        attr["perm"] = int(
                            permission,
                        )

                config["attr"] = attr

            return builder_method(
                name=name,
                namespace=namespace,
                action=action,
                mode=config.pop("mode", "one"),
                volume_path=config.pop("volume_path"),
                selector=config.pop("selector", None),
                path=config.pop("path", None),
                delay=config.pop("delay", None),
                percent=config.pop("percent", None),
                errno=config.pop("errno", None),
                methods=config.pop("methods", None),
                duration=config.pop("duration", None),
                container_names=config.pop(
                    "container_names",
                    None,
                ),
                attr=config.pop("attr", None),
                mistake=config.pop("mistake", None),
            )

        if kind == "TimeChaos":
            config.pop("action", None)

            manifest = builder_method(
                name=name,
                namespace=namespace,
                mode=config.pop("mode", "one"),
                clock=config.pop("clock"),
                offset=config.pop("offset"),
                selector=config.pop("selector", None),
                container_names=config.pop(
                    "container_names",
                    None,
                ),
                pid=config.pop("pid", None),
                duration=config.pop("duration", None),
            )

            spec = manifest.get("spec", {})

            if "offset" in spec:
                spec["timeOffset"] = spec.pop(
                    "offset"
                )

            if "clock" in spec:
                clock = spec.pop("clock")

                if isinstance(clock, list):
                    spec["clockIds"] = clock
                else:
                    spec["clockIds"] = [clock]

            manifest["spec"] = spec

            return manifest

        if kind == "KernelChaos":
            config.pop("action", None)

            manifest = builder_method(
                name=name,
                namespace=namespace,
                mode=config.pop("mode", "one"),
                fail_kern=config.pop("fail_kern"),
                selector=config.pop("selector", None),
                duration=config.pop("duration", None),
            )

            spec = manifest.get("spec", {})

            if "failKern" in spec:
                spec["failKernRequest"] = spec.pop(
                    "failKern"
                )

            manifest["spec"] = spec

            return manifest

        if kind == "AWSChaos":
            config.pop("mode", None)
            config.pop("selector", None)

            return builder_method(
                name=name,
                namespace=namespace,
                action=action,
                aws_region=config.pop("aws_region"),
                ec2_instance=config.pop("ec2_instance"),
                secret_name=config.pop(
                    "secret_name",
                    None,
                ),
                duration=config.pop("duration", None),
            )

        if kind == "JVMChaos":
            config.pop("action", None)

            if "class" in config and "class_name" not in config:
                config["class_name"] = config.pop("class")

            return builder_method(
                name=name,
                namespace=namespace,
                action=action,
                mode=config.pop("mode", "one"),
                selector=config.pop("selector", None),
                class_name=config.pop(
                    "class_name",
                    None,
                ),
                method=config.pop("method", None),
                latency=config.pop("latency", None),
                value=config.pop("value", None),
                exception=config.pop(
                    "exception",
                    None,
                ),
                cpu_count=config.pop(
                    "cpu_count",
                    None,
                ),
                mem_type=config.pop(
                    "mem_type",
                    None,
                ),
                port=config.pop("port", None),
                rule_data=config.pop(
                    "rule_data",
                    None,
                ),
            )

        if kind == "BlockChaos":
            config.pop("action", None)
            config.pop("duration", None)

            return builder_method(
                name=name,
                namespace=namespace,
                action=action,
                mode=config.pop("mode", "one"),
                volume_name=config.pop("volume_name"),
                selector=config.pop("selector", None),
                value=config.pop("value", None),
                latency=config.pop("latency", None),
            )

        if kind == "PhysicalMachineChaos":
            mode = config.pop(
                "mode",
                "one",
            )

            physical_machine = config.pop(
                "physical_machine",
                None,
            )

            value = config.pop(
                "value",
                None,
            )

            action_config = config.pop(
                "action_config",
                None,
            )

            duration = config.pop(
                "duration",
                None,
            )

            selector = {}

            if physical_machine:
                selector = {
                    "physicalMachines": {
                        namespace: [
                            physical_machine
                        ]
                    }
                }

            if action == "stress-cpu":
                cpu_load = config.pop(
                    "cpu_load",
                    10,
                )

                cpu_workers = config.pop(
                    "cpu_workers",
                    1,
                )

                action_config = {
                    "load": int(cpu_load),
                    "workers": int(cpu_workers),
                }

            return builder_method(
                name=name,
                namespace=namespace,
                action=action,
                mode=mode,
                selector=selector,
                action_config=action_config,
                duration=duration,
            )

        if kind == "Workflow":
            templates = config.pop(
                "templates"
            )

            normalized_templates = []

            for template in templates:
                template = dict(template)

                task = template.get("task")

                if isinstance(task, dict):
                    task = dict(task)

                    container = task.get(
                        "container"
                    )

                    if isinstance(container, str):
                        task["container"] = {
                            "name": container,
                            "command": task.get(
                                "command",
                                [],
                            ),
                        }

                    task.pop(
                        "command",
                        None,
                    )

                    template["task"] = task

                normalized_templates.append(
                    template
                )

            return builder_method(
                name=name,
                namespace=namespace,
                entry=config.pop("entry"),
                templates=normalized_templates,
            )

        if kind == "Schedule":
            return builder_method(
                name=name,
                namespace=namespace,
                schedule=config.pop("schedule"),
                experiment_type=config.pop("type"),
                experiment_spec=config.pop("chaos"),
                history_limit=config.pop(
                    "history_limit",
                    None,
                ),
                concurrency_policy=config.pop(
                    "concurrency_policy",
                    None,
                ),
                starting_deadline_seconds=config.pop(
                    "starting_deadline_seconds",
                    None,
                ),
            )

        if kind == "StatusCheck":
            templates = config.pop("templates", [])

            if not templates:
                raise ValueError(
                    "StatusCheck requires at least one template."
                )

            status_template_config = templates[0]

            status_check = status_template_config.get(
                "status_check",
                {},
            )

            url = status_check.get("url")

            if not url:
                raise ValueError(
                    "StatusCheck requires status_check.url."
                )

            status_code = str(
                status_check.get(
                    "status_code",
                    config.pop("status_code", "200"),
                )
            )

            status_template = self.builder.build_status_check(
                name=status_template_config.get(
                    "name",
                    "status-check",
                ),
                url=url,
                status_code=status_code,
                namespace=namespace,
                mode=status_check.get(
                    "mode",
                    "Synchronous",
                ),
                method=status_check.get(
                    "method",
                    "GET",
                ),
            )

            return self.builder.build_workflow(
                name=name,
                namespace=namespace,
                entry=status_template["name"],
                templates=[status_template],
            )

        #
        # PodChaos / NetworkChaos / DNSChaos use the common
        # action + mode + selector builder contract.
        #
        if kind == "NetworkChaos":
            config.pop("action", None)

            # Chaos Mesh models reorder as part of
            # Netem's delay specification, not as a standalone
            # NetworkChaos action.

            network_action = action

            if action == "delay":
                latency = config.pop("delay", None)

                if isinstance(latency, str):
                    config["delay"] = {
                        "latency": latency,
                    }
                if config.get("jitter"):
                    config["delay"]["jitter"] = config.pop("jitter")
                if config.get("correlation") is not None:
                    config["delay"]["correlation"] = str(config.pop("correlation"))

            elif action == "loss":
                loss = config.pop("loss", None)

                if isinstance(loss, str):
                    config["loss"] = {
                        "loss": loss,
                    }
                if config.get("correlation") is not None:
                    config["loss"]["correlation"] = str(config.pop("correlation"))

            elif action == "duplicate":
                duplicate = config.pop("duplicate", None)

                if isinstance(duplicate, str):
                    config["duplicate"] = {
                        "duplicate": duplicate,
                    }
                if config.get("correlation") is not None:
                    config["duplicate"]["correlation"] = str(config.pop("correlation"))

            elif action == "corrupt":
                corrupt = config.pop("corrupt", None)

                if isinstance(corrupt, str):
                    config["corrupt"] = {
                        "corrupt": corrupt,
                    }
                if config.get("correlation") is not None:
                    config["corrupt"]["correlation"] = str(config.pop("correlation"))

            elif action == "reorder":
                reorder = config.pop("reorder", None)
                latency = config.pop(
                    "latency",
                    "100ms",
                )

                if isinstance(reorder, str):
                    reorder = {
                        "reorder": reorder,
                        "gap": 1,
                    }

                elif isinstance(reorder, dict):
                    reorder = dict(reorder)

                if reorder:
                    config["delay"] = {
                        "latency": latency,
                        "reorder": reorder,
                    }

                network_action = "netem"

            elif action == "bandwidth":
                rate = config.pop("rate", None)

                if isinstance(rate, str):
                    config["rate"] = {
                        "rate": rate,
                        "buffer": 10000,
                        "limit": 10000,
                    }

            return builder_method(
                name=name,
                namespace=namespace,
                action=network_action,
                mode=config.pop("mode", "one"),
                selector=config.pop("selector", None),
                duration=config.pop("duration", None),
                value=config.pop("value", None),
                direction=config.pop("direction", None),
                target=config.pop("target", None),
                delay=config.pop("delay", None),
                loss=config.pop("loss", None),
                duplicate=config.pop("duplicate", None),
                corrupt=config.pop("corrupt", None),
                reorder=config.pop("reorder", None),
                rate=config.pop("rate", None),
                bandwidth=config.pop("bandwidth", None),
                external_targets=config.pop(
                    "external_targets",
                    None,
                ),
                device=config.pop("device", None),
            )

        if kind in {
            "PodChaos",
            "DNSChaos",
        }:
            # Shared AKS/EKS lifecycle context is not part of a Chaos Mesh spec.
            for key in {
                "target_mode",
                "owning_deployment",
                "label_key",
                "label_val",
            }:
                config.pop(key, None)
            return builder_method(
                name=name,
                namespace=namespace,
                action=action,
                **config,
            )

        raise ValueError(
            f"Unsupported Chaos Mesh kind '{kind}'."
        )

    def _validate_target(
        self,
        cluster: str,
        namespace: str,
        pod: str | None,
        deployment: str | None,
        node: str | None,
    ) -> None:

        if self.target_resolver is None:
            return

        if node:
            self.target_resolver.resolve_node(
                cluster,
                node,
            )
            return

        if pod:
            self.target_resolver.resolve_pod(
                cluster,
                namespace,
                pod,
            )
            return

        if deployment:
            self.target_resolver.resolve_deployment(
                cluster,
                namespace,
                deployment,
            )
            return

        self.target_resolver.resolve_namespace(
            cluster,
            namespace,
        )

    @classmethod
    def _validate_manifest(
        cls,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:

        missing = [
            field
            for field in cls.REQUIRED_MANIFEST_FIELDS
            if field not in manifest
        ]

        if missing:
            raise ValueError(
                "Chaos Mesh manifest is missing required "
                f"fields: {', '.join(missing)}"
            )

        return dict(manifest)

    @staticmethod
    def _pod_selector(
        namespace: str | None = None,
        pod: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:

        selector: dict[str, Any] = {}

        if namespace:
            selector["namespaces"] = [
                namespace
            ]

        if pod and namespace:
            selector["pods"] = {
                namespace: [pod]
            }

        if labels:
            selector["labelSelectors"] = dict(
                labels
            )

        return selector

    @staticmethod
    def _load_definition(
        path: str,
    ) -> dict[str, Any]:

        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Chaos Mesh experiment definition not found: {path}"
            )

        with open(
            path,
            "r",
            encoding="utf-8",
        ) as handle:
            definition = json.load(handle)

        if not isinstance(definition, dict):
            raise TypeError(
                "Chaos Mesh experiment definition "
                "must be a JSON object."
            )

        return definition

    @staticmethod
    def _kind_to_method(
        kind: str,
    ) -> str:

        mapping = {
            "PodChaos": "pod_chaos",
            "NetworkChaos": "network_chaos",
            "DNSChaos": "dns_chaos",
            "HTTPChaos": "http_chaos",
            "IOChaos": "io_chaos",
            "StressChaos": "stress_chaos",
            "TimeChaos": "time_chaos",
            "KernelChaos": "kernel_chaos",
            "AWSChaos": "aws_chaos",
            "JVMChaos": "jvm_chaos",
            "BlockChaos": "block_chaos",
            "PhysicalMachineChaos": "physical_machine_chaos",
            "Workflow": "workflow",
            "Schedule": "schedule",
            "StatusCheck": "status_check",
        }

        try:
            return mapping[kind]
        except KeyError as exc:
            raise ValueError(
                f"Unsupported Chaos Mesh kind '{kind}'."
            ) from exc

    @staticmethod
    def _resource_name(
        experiment: Any,
        kind: str,
        action: str | None,
    ) -> str:

        experiment_id = str(
            getattr(
                experiment,
                "id",
                "chaos",
            )
        )

        experiment_id = (
            experiment_id
            .lower()
            .replace("_", "-")
            .replace(" ", "-")
        )

        suffix = (
            str(action)
            .lower()
            .replace("_", "-")
            if action
            else kind.lower()
        )

        return (
            f"chaosforge-{experiment_id}-{suffix}"
        )[:253]
