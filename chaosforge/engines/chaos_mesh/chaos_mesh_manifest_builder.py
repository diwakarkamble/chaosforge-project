from typing import Any

from chaosforge.engines.chaos_mesh.chaos_mesh_capabilities import (
    is_supported_chaos_mesh_kind,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_models import ChaosMeshExperiment


class ChaosMeshManifestBuilder:
    """
    Builds Kubernetes manifests for Chaos Mesh experiments.

    The builder keeps ChaosForge-specific input normalization separate
    from the Kubernetes client that submits the resulting CRD.
    """

    API_VERSION = "chaos-mesh.org/v1alpha1"

    def build(
        self,
        kind: str,
        name: str,
        namespace: str = "default",
        spec: dict[str, Any] | None = None,
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Build a Chaos Mesh manifest from an already normalized spec.
        """

        if not is_supported_chaos_mesh_kind(kind):
            raise ValueError(
                f"Unsupported Chaos Mesh kind: '{kind}'."
            )

        if not name:
            raise ValueError("Chaos Mesh resource name is required.")

        if not namespace:
            raise ValueError("Chaos Mesh namespace is required.")

        experiment = ChaosMeshExperiment(
            kind=kind,
            name=name,
            namespace=namespace,
            api_version=self.API_VERSION,
            spec=dict(spec or {}),
            labels=dict(labels or {}),
            annotations=dict(annotations or {}),
        )

        return experiment.to_manifest()

    def build_pod_chaos(
        self,
        name: str,
        action: str,
        mode: str,
        namespace: str = "default",
        selector: dict[str, Any] | None = None,
        duration: str | None = None,
        value: str | None = None,
        container_names: list[str] | None = None,
        grace_period: int | None = None,
    ) -> dict[str, Any]:
        """
        Build a PodChaos manifest.

        Supported actions follow the current Chaos Mesh PodChaos model:
        pod-failure, pod-kill, and container-kill.
        """

        supported_actions = {
            "pod-failure",
            "pod-kill",
            "container-kill",
        }

        if action not in supported_actions:
            raise ValueError(
                f"Unsupported PodChaos action: '{action}'. "
                f"Supported actions: {sorted(supported_actions)}"
            )

        spec: dict[str, Any] = {
            "action": action,
            "mode": mode,
            "selector": selector or {},
        }

        if value is not None:
            spec["value"] = value

        if duration is not None:
            spec["duration"] = duration

        if container_names is not None:
            spec["containerNames"] = list(container_names)

        if grace_period is not None:
            spec["gracePeriod"] = grace_period

        return self.build(
            kind="PodChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_network_chaos(
        self,
        name: str,
        action: str,
        mode: str,
        namespace: str = "default",
        selector: dict[str, Any] | None = None,
        duration: str | None = None,
        value: str | None = None,
        direction: str | None = None,
        target: dict[str, Any] | None = None,
        delay: dict[str, Any] | None = None,
        loss: str | None = None,
        duplicate: str | None = None,
        corrupt: str | None = None,
        reorder: dict[str, Any] | None = None,
        rate: dict[str, Any] | None = None,
        bandwidth: dict[str, Any] | None = None,
        external_targets: list[str] | None = None,
        device: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a NetworkChaos manifest.
        """

        supported_actions = {
            "netem",
            "delay",
            "loss",
            "duplicate",
            "corrupt",
            "reorder",
            "partition",
            "bandwidth",
        }

        if action not in supported_actions:
            raise ValueError(
                f"Unsupported NetworkChaos action: '{action}'. "
                f"Supported actions: {sorted(supported_actions)}"
            )

        spec: dict[str, Any] = {
            "action": action,
            "mode": mode,
            "selector": selector or {},
        }

        optional_values = {
            "value": value,
            "direction": direction,
            "target": target,
            "delay": delay,
            "loss": loss,
            "duplicate": duplicate,
            "corrupt": corrupt,
            "reorder": reorder,
            "rate": rate,
            "bandwidth": bandwidth,
            "externalTargets": external_targets,
            "device": device,
            "duration": duration,
        }

        for key, item in optional_values.items():
            if item is not None:
                spec[key] = item

        return self.build(
            kind="NetworkChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_dns_chaos(
        self,
        name: str,
        action: str,
        mode: str,
        namespace: str = "default",
        selector: dict[str, Any] | None = None,
        patterns: list[str] | None = None,
        value: str | None = None,
        duration: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a DNSChaos manifest.
        """

        if action not in {"random", "error"}:
            raise ValueError(
                "DNSChaos action must be 'random' or 'error'."
            )

        spec: dict[str, Any] = {
            "action": action,
            "mode": mode,
            "selector": selector or {},
        }

        if patterns is not None:
            spec["patterns"] = list(patterns)

        if value is not None:
            spec["value"] = value

        if duration is not None:
            spec["duration"] = duration

        return self.build(
            kind="DNSChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_http_chaos(
        self,
        name: str,
        mode: str,
        namespace: str = "default",
        selector: dict[str, Any] | None = None,
        target: str = "Request",
        port: int | None = None,
        method: str | None = None,
        path: str | None = None,
        duration: str | None = None,
        abort: bool | None = None,
        delay: str | None = None,
        replace: dict[str, Any] | None = None,
        patch: dict[str, Any] | None = None,
        request_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Build an HTTPChaos manifest.
        """

        if target not in {"Request", "Response"}:
            raise ValueError(
                "HTTPChaos target must be 'Request' or 'Response'."
            )

        spec: dict[str, Any] = {
            "mode": mode,
            "selector": selector or {},
            "target": target,
        }

        # HTTPChaos expects port as an integer.
        if port is not None:
            try:
                port = int(port)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"HTTPChaos port must be an integer, got: {port!r}"
                ) from exc

        optional_values = {
            "port": port,
            "method": method,
            "path": path,
            "duration": duration,
            "abort": abort,
            "delay": delay,
            "replace": replace,
            "patch": patch,
            "request_headers": request_headers,
        }

        for key, item in optional_values.items():
            if item is not None:
                spec[key] = item

        return self.build(
            kind="HTTPChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_io_chaos(
        self,
        name: str,
        action: str,
        mode: str,
        volume_path: str,
        namespace: str = "default",
        selector: dict[str, Any] | None = None,
        path: str | None = None,
        delay: str | None = None,
        percent: int | None = None,
        errno: int | None = None,
        methods: list[str] | None = None,
        duration: str | None = None,
        container_names: list[str] | None = None,
        attr: dict[str, Any] | None = None,
        mistake: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Build an IOChaos manifest.
        """

        supported_actions = {
            "latency",
            "fault",
            "attrOverride",
            "mistake",
        }

        if action not in supported_actions:
            raise ValueError(
                f"Unsupported IOChaos action: '{action}'. "
                f"Supported actions: {sorted(supported_actions)}"
            )

        if not volume_path:
            raise ValueError(
                "IOChaos volume_path is required."
            )

        spec: dict[str, Any] = {
            "action": action,
            "mode": mode,
            "selector": selector or {},
            "volumePath": volume_path,
        }

        optional_values = {
            "path": path,
            "delay": delay,
            "percent": percent,
            "errno": errno,
            "methods": methods,
            "duration": duration,
            "containerNames": container_names,
            "attr": attr,
            "mistake": mistake,
        }

        for key, item in optional_values.items():
            if item is not None:
                spec[key] = item

        return self.build(
            kind="IOChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_stress_chaos(
        self,
        name: str,
        mode: str,
        stressors: dict[str, Any],
        namespace: str = "default",
        selector: dict[str, Any] | None = None,
        duration: str | None = None,
        value: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a StressChaos manifest.
        """

        if not stressors:
            raise ValueError(
                "StressChaos requires at least one stressor."
            )

        spec: dict[str, Any] = {
            "mode": mode,
            "selector": selector or {},
            "stressors": stressors,
        }

        if duration is not None:
            spec["duration"] = duration

        if value is not None:
            spec["value"] = value

        return self.build(
            kind="StressChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_time_chaos(
        self,
        name: str,
        mode: str,
        clock: str,
        offset: str,
        namespace: str = "default",
        selector: dict[str, Any] | None = None,
        container_names: list[str] | None = None,
        pid: int | None = None,
        duration: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a TimeChaos manifest.

        TimeChaos changes the perceived clock of the selected process
        or containers by the requested offset.
        """

        if mode not in {
            "one",
            "all",
            "fixed",
            "fixed-percent",
            "random-max-percent",
        }:
            raise ValueError(
                f"Unsupported TimeChaos mode: '{mode}'."
            )

        if not clock:
            raise ValueError("TimeChaos clock is required.")

        if not offset:
            raise ValueError("TimeChaos offset is required.")

        spec: dict[str, Any] = {
            "mode": mode,
            "clock": clock,
            "offset": offset,
            "selector": selector or {},
        }

        if container_names is not None:
            spec["containerNames"] = list(container_names)

        if pid is not None:
            spec["pid"] = pid

        if duration is not None:
            spec["duration"] = duration

        return self.build(
            kind="TimeChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_kernel_chaos(
        self,
        name: str,
        mode: str,
        fail_kern: dict[str, Any],
        namespace: str = "default",
        selector: dict[str, Any] | None = None,
        duration: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a KernelChaos manifest.

        The failKern payload is intentionally supplied as a dictionary
        because kernel fault parameters are kernel-specific.
        """

        if not fail_kern:
            raise ValueError(
                "KernelChaos requires fail_kern configuration."
            )

        if mode not in {
            "one",
            "all",
            "fixed",
            "fixed-percent",
            "random-max-percent",
        }:
            raise ValueError(
                f"Unsupported KernelChaos mode: '{mode}'."
            )

        spec: dict[str, Any] = {
            "mode": mode,
            "selector": selector or {},
            "failKern": dict(fail_kern),
        }

        if duration is not None:
            spec["duration"] = duration

        return self.build(
            kind="KernelChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_aws_chaos(
        self,
        name: str,
        action: str,
        aws_region: str,
        ec2_instance: str,
        namespace: str = "default",
        secret_name: str | None = None,
        duration: str | None = None,
        mode: str | None = None,
        value: str | None = None,
        volume_id: str | None = None,
        device_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Build an AWSChaos manifest.

        Current Chaos Mesh 2.8.x documentation describes EC2 stop,
        EC2 restart, and volume detach operations.
        """

        supported_actions = {
            "ec2-stop",
            "ec2-restart",
            "detach-volume",
        }

        if action not in supported_actions:
            raise ValueError(
                f"Unsupported AWSChaos action: '{action}'. "
                f"Supported actions: {sorted(supported_actions)}"
            )

        if not aws_region:
            raise ValueError(
                "AWSChaos aws_region is required."
            )

        if not ec2_instance:
            raise ValueError(
                "AWSChaos ec2_instance is required."
            )

        if action == "detach-volume":
            if not volume_id:
                raise ValueError(
                    "AWSChaos detach-volume requires volume_id."
                )

            if not device_name:
                raise ValueError(
                    "AWSChaos detach-volume requires device_name."
                )

        spec: dict[str, Any] = {
            "action": action,
            "awsRegion": aws_region,
            "ec2Instance": ec2_instance,
        }

        if secret_name is not None:
            spec["secretName"] = secret_name

        if duration is not None:
            spec["duration"] = duration

        if mode is not None:
            spec["mode"] = mode

        if value is not None:
            spec["value"] = value

        if volume_id is not None:
            spec["volumeID"] = volume_id

        if device_name is not None:
            spec["deviceName"] = device_name

        return self.build(
            kind="AWSChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )
    def build_jvm_chaos(
        self,
        name: str,
        action: str,
        mode: str,
        namespace: str = "default",
        selector: dict[str, Any] | None = None,
        class_name: str | None = None,
        method: str | None = None,
        latency: int | None = None,
        value: str | None = None,
        exception: str | None = None,
        cpu_count: int | None = None,
        mem_type: str | None = None,
        port: int | None = None,
        rule_data: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a JVMChaos manifest.

        JVMChaos uses Byteman to inject faults into Java applications.
        """

        supported_actions = {
            "latency",
            "return",
            "exception",
            "stress",
            "gc",
            "ruleData",
        }

        supported_modes = {
            "one",
            "all",
            "fixed",
            "fixed-percent",
            "random-max-percent",
        }

        if action not in supported_actions:
            raise ValueError(
                f"Unsupported JVMChaos action: '{action}'. "
                f"Supported actions: {sorted(supported_actions)}"
            )

        if mode not in supported_modes:
            raise ValueError(
                f"Unsupported JVMChaos mode: '{mode}'."
            )

        if not selector:
            raise ValueError(
                "JVMChaos selector is required."
            )

        spec: dict[str, Any] = {
            "action": action,
            "mode": mode,
            "selector": dict(selector),
        }

        if action in {"latency", "return", "exception"}:
            if not class_name:
                raise ValueError(
                    f"JVMChaos action '{action}' requires class_name."
                )

            if not method:
                raise ValueError(
                    f"JVMChaos action '{action}' requires method."
                )

            spec["class"] = class_name
            spec["method"] = method

        if action == "latency":
            if latency is None:
                raise ValueError(
                    "JVMChaos latency action requires latency."
                )

            spec["latency"] = latency

        elif action == "return":
            if value is None:
                raise ValueError(
                    "JVMChaos return action requires value."
                )

            spec["value"] = value

        elif action == "exception":
            if exception is None:
                raise ValueError(
                    "JVMChaos exception action requires exception."
                )

            spec["exception"] = exception

        elif action == "stress":
            if cpu_count is None and mem_type is None:
                raise ValueError(
                    "JVMChaos stress action requires cpu_count "
                    "or mem_type."
                )

            if cpu_count is not None:
                spec["cpuCount"] = cpu_count

            if mem_type is not None:
                if mem_type not in {"heap", "stack"}:
                    raise ValueError(
                        "JVMChaos mem_type must be 'heap' or 'stack'."
                    )

                spec["memType"] = mem_type

        elif action == "ruleData":
            if rule_data is None:
                raise ValueError(
                    "JVMChaos ruleData action requires rule_data."
                )

            spec["ruleData"] = rule_data

        if port is not None:
            spec["port"] = port

        return self.build(
            kind="JVMChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_block_chaos(
        self,
        name: str,
        action: str,
        mode: str,
        volume_name: str,
        namespace: str = "default",
        selector: dict[str, Any] | None = None,
        value: str | None = None,
        latency: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a BlockChaos manifest.

        BlockChaos supports delay and freeze actions.
        """

        supported_actions = {
            "delay",
            "freeze",
        }

        supported_modes = {
            "one",
            "all",
            "fixed",
            "fixed-percent",
            "random-max-percent",
        }

        if action not in supported_actions:
            raise ValueError(
                f"Unsupported BlockChaos action: '{action}'."
            )

        if mode not in supported_modes:
            raise ValueError(
                f"Unsupported BlockChaos mode: '{mode}'."
            )

        if not volume_name:
            raise ValueError(
                "BlockChaos volume_name is required."
            )

        if not selector:
            raise ValueError(
                "BlockChaos selector is required."
            )

        spec: dict[str, Any] = {
            "mode": mode,
            "selector": dict(selector),
            "volumeName": volume_name,
            "action": action,
        }

        if value is not None:
            spec["value"] = value

        if action == "delay":
            if not latency:
                raise ValueError(
                    "BlockChaos delay action requires latency."
                )

            spec["delay"] = {
                "latency": latency,
            }

        return self.build(
            kind="BlockChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_physical_machine_chaos(
        self,
        name: str,
        action: str,
        mode: str,
        selector: dict[str, Any],
        namespace: str = "default",
        action_config: dict[str, Any] | None = None,
        duration: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a PhysicalMachineChaos manifest.

        PhysicalMachineChaos requires Chaosd on the target machines.
        """

        supported_actions = {
            "stress-cpu",
            "stress-mem",
            "disk-read-payload",
            "disk-write-payload",
            "disk-fill",
            "network-corrupt",
            "network-duplicate",
            "network-loss",
            "network-delay",
            "network-partition",
            "network-dns",
            "process",
            "jvm-exception",
            "jvm-gc",
            "jvm-latency",
            "jvm-return",
            "jvm-stress",
            "jvm-rule-data",
            "clock",
        }

        supported_modes = {
            "one",
            "all",
            "fixed",
            "fixed-percent",
            "random-max-percent",
        }

        if action not in supported_actions:
            raise ValueError(
                f"Unsupported PhysicalMachineChaos action: '{action}'."
            )

        if mode not in supported_modes:
            raise ValueError(
                f"Unsupported PhysicalMachineChaos mode: '{mode}'."
            )

        if not selector:
            raise ValueError(
                "PhysicalMachineChaos selector is required."
            )

        spec: dict[str, Any] = {
            "action": action,
            "mode": mode,
            "selector": dict(selector),
        }

        if action_config:
            config_key_map = {
                "network-delay": "network-delay",
                "network-loss": "network-loss",
                "network-corrupt": "network-corrupt",
                "network-duplicate": "network-duplicate",
                "network-partition": "network-partition",
                "network-dns": "network-dns",
                "stress-cpu": "stress-cpu",
                "stress-mem": "stress-mem",
                "disk-read-payload": "disk-read-payload",
                "disk-write-payload": "disk-write-payload",
                "disk-fill": "disk-fill",
                "process": "process",
                "jvm-exception": "jvm-exception",
                "jvm-gc": "jvm-gc",
                "jvm-latency": "jvm-latency",
                "jvm-return": "jvm-return",
                "jvm-stress": "jvm-stress",
                "jvm-rule-data": "jvm-rule-data",
                "clock": "clock",
            }

            spec[config_key_map[action]] = dict(action_config)

        if duration is not None:
            spec["duration"] = duration

        return self.build(
            kind="PhysicalMachineChaos",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_workflow(
        self,
        name: str,
        entry: str,
        templates: list[dict[str, Any]],
        namespace: str = "default",
    ) -> dict[str, Any]:
        """
        Build a Chaos Mesh Workflow manifest.
        """

        if not entry:
            raise ValueError(
                "Workflow entry is required."
            )

        if not templates:
            raise ValueError(
                "Workflow templates are required."
            )

        template_names = {
            template.get("name")
            for template in templates
            if isinstance(template, dict)
        }

        if entry not in template_names:
            raise ValueError(
                f"Workflow entry '{entry}' does not match "
                "any template name."
            )

        for template in templates:
            if not isinstance(template, dict):
                raise TypeError(
                    "Workflow templates must be dictionaries."
                )

            if not template.get("name"):
                raise ValueError(
                    "Every Workflow template requires a name."
                )

            if not template.get("templateType"):
                raise ValueError(
                    f"Workflow template '{template['name']}' "
                    "requires templateType."
                )

        return self.build(
            kind="Workflow",
            name=name,
            namespace=namespace,
            spec={
                "entry": entry,
                "templates": list(templates),
            },
        )

    def build_schedule(
        self,
        name: str,
        schedule: str,
        experiment_type: str,
        experiment_spec: dict[str, Any],
        namespace: str = "default",
        history_limit: int | None = None,
        concurrency_policy: str | None = None,
        starting_deadline_seconds: int | None = None,
    ) -> dict[str, Any]:
        """
        Build a Chaos Mesh Schedule manifest.
        """

        if not schedule:
            raise ValueError(
                "Schedule expression is required."
            )

        if not experiment_type:
            raise ValueError(
                "Schedule experiment_type is required."
            )

        if not experiment_spec:
            raise ValueError(
                "Schedule experiment_spec is required."
            )

        supported_policies = {
            "Allow",
            "Forbid",
            "",
        }

        if (
            concurrency_policy is not None
            and concurrency_policy not in supported_policies
        ):
            raise ValueError(
                "Schedule concurrency_policy must be "
                f"one of {sorted(supported_policies)}."
            )

        spec: dict[str, Any] = {
            "schedule": schedule,
            "type": experiment_type,
        }

        if history_limit is not None:
            try:
                history_limit = int(history_limit)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Schedule history_limit must be an integer."
                ) from exc

            spec["historyLimit"] = history_limit

        if concurrency_policy is not None:
            spec["concurrencyPolicy"] = concurrency_policy

        if starting_deadline_seconds is not None:
            spec["startingDeadlineSeconds"] = (
                starting_deadline_seconds
            )

        chaos_key = experiment_type[:1].lower() + experiment_type[1:]

        spec[chaos_key] = dict(experiment_spec)

        return self.build(
            kind="Schedule",
            name=name,
            namespace=namespace,
            spec=spec,
        )

    def build_status_check(
        self,
        name: str,
        url: str,
        status_code: str,
        namespace: str = "default",
        mode: str = "Synchronous",
        method: str = "GET",
        headers: dict[str, list[str]] | None = None,
        body: str | None = None,
        interval_seconds: int | None = None,
        timeout_seconds: int | None = None,
        failure_threshold: int | None = None,
        success_threshold: int | None = None,
        duration: str | None = None,
        records_history_limit: int | None = None,
        abort_with_status_check: bool = False,
        deadline: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a StatusCheck Workflow template.

        StatusCheck is represented as a Workflow template rather
        than as a standalone Chaos experiment.
        """

        if not url:
            raise ValueError(
                "StatusCheck URL is required."
            )

        if not status_code:
            raise ValueError(
                "StatusCheck status_code is required."
            )

        if mode not in {
            "Synchronous",
            "Continuous",
        }:
            raise ValueError(
                "StatusCheck mode must be "
                "'Synchronous' or 'Continuous'."
            )

        if method not in {
            "GET",
            "POST",
        }:
            raise ValueError(
                "StatusCheck method must be GET or POST."
            )

        status_check: dict[str, Any] = {
            "mode": mode,
            "type": "HTTP",
            "http": {
                "url": url,
                "method": method,
                "criteria": {
                    "statusCode": status_code,
                },
            },
        }

        if headers is not None:
            status_check["http"]["headers"] = dict(headers)

        if body is not None:
            status_check["http"]["body"] = body

        if interval_seconds is not None:
            status_check["intervalSeconds"] = interval_seconds

        if timeout_seconds is not None:
            status_check["timeoutSeconds"] = timeout_seconds

        if failure_threshold is not None:
            status_check["failureThreshold"] = failure_threshold

        if success_threshold is not None:
            status_check["successThreshold"] = success_threshold

        if duration is not None:
            status_check["duration"] = duration

        if records_history_limit is not None:
            status_check["recordsHistoryLimit"] = (
                records_history_limit
            )

        template: dict[str, Any] = {
            "name": name,
            "templateType": "StatusCheck",
            "statusCheck": status_check,
            "abortWithStatusCheck": abort_with_status_check,
        }

        if deadline is not None:
            template["deadline"] = deadline

        return template
    def build_generic(
        self,
        kind: str,
        name: str,
        spec: dict[str, Any],
        namespace: str = "default",
    ) -> dict[str, Any]:
        """
        Build a manifest for a registered Chaos Mesh kind whose
        detailed schema is supplied by the caller.
        """

        return self.build(
            kind=kind,
            name=name,
            namespace=namespace,
            spec=spec,
        )
