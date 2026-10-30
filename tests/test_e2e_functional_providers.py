from types import SimpleNamespace

from e2e.webui.functional.providers import aws, azure


def test_aws_resolver_handles_name_tag_and_unsupported_components(monkeypatch):
    class Session:
        def client(self, name):
            if name == "lambda":
                return SimpleNamespace(
                    get_paginator=lambda _: SimpleNamespace(
                        paginate=lambda: [{"Functions": [{"FunctionArn": "arn:one", "FunctionName": "one"}]}]
                    )
                )
            if name == "elbv2":
                return SimpleNamespace(
                    get_paginator=lambda _: SimpleNamespace(
                        paginate=lambda: [{"LoadBalancers": [{"LoadBalancerArn": "arn:elb:one", "LoadBalancerName": "one"}]}]
                    )
                )
            if name == "elasticache":
                return SimpleNamespace(
                    get_paginator=lambda _: SimpleNamespace(
                        paginate=lambda: [{"ReplicationGroups": [{"ARN": "arn:cache:one", "ReplicationGroupId": "one"}]}]
                    )
                )
            return SimpleNamespace(
                get_paginator=lambda _: SimpleNamespace(
                    paginate=lambda **_: [{"ResourceTagMappingList": [{"ResourceARN": "arn:aws:lambda:x:function:one"}]}]
                )
            )

    monkeypatch.setitem(__import__("sys").modules, "boto3", SimpleNamespace(Session=lambda **_: Session()))
    base = {"service": "lambda", "region": "eu-central-1"}

    assert aws.resolve({**base, "target_type": "name", "target": "one"})[0] == "found"
    assert aws.resolve({**base, "target_type": "tags", "target": {"ManagedBy": "ChaosForge"}})[0] == "found"
    assert aws.resolve({**base, "service": "ec2", "target_type": "name", "target": "one"})[0] == "missing"
    assert aws.resolve({**base, "service": "elb", "target_type": "name", "target": "one"})[0] == "found"
    assert aws.resolve({**base, "service": "elasticache", "target_type": "name", "target": "one"})[0] == "found"


def test_aws_graph_resolves_unique_untaggable_child_under_tagged_parent(monkeypatch):
    class Session:
        def client(self, name):
            if name == "resourcegroupstaggingapi":
                return SimpleNamespace(get_paginator=lambda _: SimpleNamespace(
                    paginate=lambda **_: [{"ResourceTagMappingList": [{"ResourceARN": "api-1"}]}]
                ))
            if name == "apigateway":
                return SimpleNamespace(
                    get_paginator=lambda operation: SimpleNamespace(
                        paginate=lambda **_: ([{"items": [{"id": "api-1", "name": "orders"}]}]
                                               if operation == "get_rest_apis"
                                               else [{"item": [{"stageName": "test"}]}])
                    ),
                    get_stages=lambda **_: {"item": [{"stageName": "test"}]},
                )
            raise AssertionError(name)

    monkeypatch.setitem(__import__("sys").modules, "boto3", SimpleNamespace(Session=lambda **_: Session()))
    status, graph, reason = aws.resolve_graph(
        {"region": "eu-central-1", "target_type": "tags", "target": {"ManagedBy": "ChaosForge"}},
        [
            {"name": "rest_api_id", "resource_type": "apigateway"},
            {"name": "stage_name", "resource_type": "apigateway-stage", "parent": "rest_api_id"},
        ],
    )

    assert (status, reason) == ("found", "")
    assert graph == {
        "rest_api_id": {"id": "api-1", "name": "orders", "arn": "api-1"},
        "stage_name": {"id": "test", "name": "test", "arn": "test"},
    }


def test_aws_graph_requires_exactly_one_child_even_when_parent_is_tagged(monkeypatch):
    class Session:
        def client(self, name):
            if name == "resourcegroupstaggingapi":
                return SimpleNamespace(get_paginator=lambda _: SimpleNamespace(
                    paginate=lambda **_: [{"ResourceTagMappingList": [{"ResourceARN": "api-1"}]}]
                ))
            return SimpleNamespace(
                get_paginator=lambda operation: SimpleNamespace(
                    paginate=lambda **_: ([{"items": [{"id": "api-1", "name": "orders"}]}]
                                           if operation == "get_rest_apis"
                                           else [{"item": [{"stageName": "blue"}, {"stageName": "green"}]}])
                ),
                get_stages=lambda **_: {"item": [{"stageName": "blue"}, {"stageName": "green"}]},
            )

    monkeypatch.setitem(__import__("sys").modules, "boto3", SimpleNamespace(Session=lambda **_: Session()))
    status, graph, reason = aws.resolve_graph(
        {"region": "eu-central-1", "target_type": "tags", "target": {"ManagedBy": "ChaosForge"}},
        [
            {"name": "rest_api_id", "resource_type": "apigateway"},
            {"name": "stage_name", "resource_type": "apigateway-stage", "parent": "rest_api_id"},
        ],
    )

    assert status == "ambiguous"
    assert graph == {"rest_api_id": {"id": "api-1", "name": "orders", "arn": "api-1"}}
    assert "stage_name" in reason


def test_aws_graph_resolves_a_tagged_kinesis_stream_to_its_arn(monkeypatch):
    class Session:
        def client(self, name):
            if name == "resourcegroupstaggingapi":
                return SimpleNamespace(get_paginator=lambda _: SimpleNamespace(
                    paginate=lambda **_: [{"ResourceTagMappingList": [{
                        "ResourceARN": "arn:aws:kinesis:eu-central-1:123:stream/orders",
                    }]}]
                ))
            if name == "kinesis":
                return SimpleNamespace(
                    get_paginator=lambda _: SimpleNamespace(
                        paginate=lambda: [{"StreamNames": ["orders"]}]
                    ),
                    describe_stream_summary=lambda **_: {
                        "StreamDescriptionSummary": {
                            "StreamARN": "arn:aws:kinesis:eu-central-1:123:stream/orders",
                        }
                    },
                )
            raise AssertionError(name)

    monkeypatch.setitem(__import__("sys").modules, "boto3", SimpleNamespace(Session=lambda **_: Session()))
    status, graph, reason = aws.resolve_graph(
        {"region": "eu-central-1", "target_type": "tags", "target": {"Chaosforge": "E2E-Test"}},
        [{"name": "target_arn", "resource_type": "kinesis"}],
    )

    assert (status, reason) == ("found", "")
    assert graph["target_arn"] == {
        "id": "arn:aws:kinesis:eu-central-1:123:stream/orders",
        "name": "orders",
        "arn": "arn:aws:kinesis:eu-central-1:123:stream/orders",
    }


def test_security_group_rule_ids_map_to_web_ingress_rule_indices():
    permissions = [
        {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
        {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
    ]
    rules = [
        {"SecurityGroupRuleId": "sgr-ssh", "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "CidrIpv4": "0.0.0.0/0"},
        {"SecurityGroupRuleId": "sgr-http", "IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "CidrIpv4": "0.0.0.0/0"},
    ]

    resources = [
        aws._item(str(index), aws._security_group_rule_id(permission, rules))
        for index, permission in enumerate(permissions)
    ]

    assert aws._match(resources, "sgr-http") == [{"id": "1", "name": "sgr-http", "arn": "1"}]
    assert aws._match(resources, "0") == [{"id": "0", "name": "sgr-ssh", "arn": "0"}]


def test_route_children_exclude_local_routes_and_use_web_indices():
    session = SimpleNamespace(
        client=lambda _: SimpleNamespace(
            get_paginator=lambda _: SimpleNamespace(
                paginate=lambda **_: [{"RouteTables": [{"Routes": [
                    {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local", "Origin": "CreateRouteTable"},
                    {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-1", "Origin": "CreateRoute"},
                ]}]}]
            )
        )
    )

    assert aws._children(session, "route-table", {"id": "rtb-1"}, "route") == [
        {"id": "0", "name": "0.0.0.0/0", "arn": "0"}
    ]


def test_aws_graph_applies_tags_again_to_taggable_children(monkeypatch):
    calls = []

    class Session:
        def client(self, name):
            if name == "resourcegroupstaggingapi":
                return SimpleNamespace(get_paginator=lambda _: SimpleNamespace(
                    paginate=lambda **kwargs: calls.append(kwargs) or [{"ResourceTagMappingList": [
                        {"ResourceARN": "arn:elb:parent" if len(calls) == 1 else "arn:tg:wanted"}
                    ]}]
                ))
            if name == "elbv2":
                return SimpleNamespace(get_paginator=lambda operation: SimpleNamespace(
                    paginate=lambda **_: ([{"LoadBalancers": [{
                        "LoadBalancerArn": "arn:elb:parent", "LoadBalancerName": "parent",
                    }]}] if operation == "describe_load_balancers" else [{"TargetGroups": [
                        {"TargetGroupArn": "arn:tg:wanted", "TargetGroupName": "wanted"},
                        {"TargetGroupArn": "arn:tg:other", "TargetGroupName": "other"},
                    ]}])
                ))
            raise AssertionError(name)

    monkeypatch.setitem(__import__("sys").modules, "boto3", SimpleNamespace(Session=lambda **_: Session()))
    status, graph, _ = aws.resolve_graph(
        {"region": "eu-central-1", "target_type": "tags", "target": {"ManagedBy": "ChaosForge"}},
        [
            {"name": "load_balancer", "resource_type": "elb"},
            {"name": "target_group", "resource_type": "elb-target-group", "parent": "load_balancer"},
        ],
    )

    assert status == "found"
    assert graph["target_group"]["id"] == "arn:tg:wanted"
    assert len(calls) == 2


def test_elasticache_security_group_child_uses_replication_group_id_not_arn():
    calls = []
    session = SimpleNamespace(
        client=lambda name: SimpleNamespace(
            describe_replication_groups=lambda **kwargs: calls.append(kwargs) or {
                "ReplicationGroups": [{"SecurityGroups": [{"SecurityGroupId": "sg-1"}]}]
            }
        )
    )

    children = aws._children(
        session,
        "elasticache-replication-group",
        {
            "id": "arn:aws:elasticache:eu-central-1:123:replicationgroup:chaosforge-e2e-redis",
            "name": "chaosforge-e2e-redis",
        },
        "security-group",
    )

    assert children == [{"id": "sg-1", "name": "sg-1", "arn": "sg-1"}]
    assert calls == [{"ReplicationGroupId": "chaosforge-e2e-redis"}]


def test_azure_resolver_handles_name_tag_and_environment_errors(monkeypatch):
    item = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/app",
        "name": "app",
        "type": "Microsoft.App/containerApps",
        "tags": {"ManagedBy": "ChaosForge  "},
    }
    _sdk(
        monkeypatch,
        "azure.mgmt.resource.resources",
        ResourceManagementClient=lambda *_: SimpleNamespace(resources=SimpleNamespace(list=lambda **_: [SimpleNamespace(**item)])),
    )
    base = {
        "service": "azure_container_apps",
        "resource_type": "Microsoft.App/containerApps",
        "subscription_id": "sub",
    }

    assert azure.resolve({**base, "target_type": "name", "target": "app"})[0] == "found"
    assert azure.resolve({**base, "target_type": "tags", "target": {"ManagedBy": "ChaosForge"}})[0] == "found"

    monkeypatch.setitem(
        __import__("sys").modules,
        "azure.mgmt.resource.resources",
        SimpleNamespace(ResourceManagementClient=lambda *_: (_ for _ in ()).throw(RuntimeError("not logged in"))),
    )
    assert azure.resolve({**base, "target_type": "name", "target": "app"})[0] == "environment_error"


def test_azure_chaos_identity_accepts_id_and_resolves_unique_name(monkeypatch):
    assert azure.resolve_chaos_identity("/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/chaos")[0] == "found"
    identities = SimpleNamespace(
        list_by_subscription=lambda: [SimpleNamespace(name="chaos", id="/identities/chaos")]
    )
    monkeypatch.setitem(__import__("sys").modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: "credential"))
    monkeypatch.setitem(
        __import__("sys").modules,
        "azure.mgmt.msi",
        SimpleNamespace(ManagedServiceIdentityClient=lambda *_: SimpleNamespace(user_assigned_identities=identities)),
    )
    assert azure.resolve_chaos_identity("chaos", "sub") == ("found", "/identities/chaos", "")


def test_azure_tagged_graph_requires_one_untaggable_child(monkeypatch):
    root = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachineScaleSets/set",
        "name": "set", "type": "Microsoft.Compute/virtualMachineScaleSets", "tags": {"E2E": "yes"},
    }
    monkeypatch.setattr(azure, "resolve_tagged_roots", lambda _: ("found", [root], ""))
    instances = SimpleNamespace(list=lambda *_: [SimpleNamespace(instance_id="0"), SimpleNamespace(instance_id="1")])
    _sdk(monkeypatch, "azure.mgmt.compute", ComputeManagementClient=lambda *_: SimpleNamespace(virtual_machine_scale_set_vms=instances))
    target = {"service": "azure_vmss", "resource_type": root["type"], "target_type": "tags", "target": {"E2E": "yes"}, "child": "instances"}
    assert azure.resolve(target)[0] == "ambiguous"


def test_azure_tagged_arm_children_must_repeat_root_tags(monkeypatch):
    root = {"id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app", "name": "app", "type": "Microsoft.Web/sites", "tags": {"E2E": "yes"}}
    slot = {"id": f"{root['id']}/slots/staging", "name": "staging", "tags": {"E2E": "no"}}

    monkeypatch.setattr(azure, "resolve_tagged_roots", lambda _: ("found", [root], ""))
    slots = SimpleNamespace(list_slots=lambda *_: [SimpleNamespace(id=slot["id"], name=slot["name"], tags=slot["tags"])])
    _sdk(monkeypatch, "azure.mgmt.web", WebSiteManagementClient=lambda *_: SimpleNamespace(web_apps=slots))
    target = {"service": "azure_app_service", "resource_type": root["type"], "target_type": "tags", "target": {"E2E": "yes"}, "child": "slots"}
    assert azure.resolve_tagged(target)[0] == "missing"


def test_azure_tagged_graph_supports_data_plane_children_and_cosmos_regions(monkeypatch):
    root = {"id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DocumentDB/databaseAccounts/db", "name": "db", "type": "Microsoft.DocumentDB/databaseAccounts", "tags": {"E2E": "yes"}, "properties": {"locations": [{"locationName": "eastus"}]}}
    monkeypatch.setattr(azure, "resolve_tagged_roots", lambda _: ("found", [root], ""))
    target = {"service": "azure_cosmos_db", "resource_type": root["type"], "target_type": "tags", "target": {"E2E": "yes"}, "child": "regions"}
    assert azure.resolve_tagged(target)[1] == [{"id": f"{root['id']}/locations/eastus", "name": "eastus"}]


def test_azure_graph_resolves_root_and_child_metadata_fields(monkeypatch):
    root = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/app",
        "name": "app", "type": "Microsoft.App/containerApps", "tags": {"E2E": "yes"},
    }

    monkeypatch.setattr(azure, "resolve_tagged_roots", lambda _: ("found", [root], ""))
    revisions = SimpleNamespace(list_revisions=lambda *_: [SimpleNamespace(name="app--blue")])
    _sdk(monkeypatch, "azure.mgmt.appcontainers", ContainerAppsAPIClient=lambda *_: SimpleNamespace(container_apps_revisions=revisions))
    target = {"service": "azure_container_apps", "resource_type": root["type"], "target_type": "tags", "target": {"E2E": "yes"}}
    status, fields, _ = azure.resolve_graph(target, [
        {"name": "resource_id", "resource_type": "azure_container_apps"},
        {"name": "revision_name", "resource_type": "azure_container_app_revisions", "parent": "resource_id"},
    ])
    assert status == "found"
    assert fields["revision_name"]["name"] == "app--blue"


def test_azure_tagged_graph_supports_all_requested_child_families(monkeypatch):
    roots = {
        "instances": "Microsoft.Compute/virtualMachineScaleSets",
        "revisions": "Microsoft.App/containerApps",
        "certificates": "Microsoft.KeyVault/vaults",
        "secrets": "Microsoft.KeyVault/vaults",
        "firewall_rules": "Microsoft.DBforPostgreSQL/flexibleServers",
    }
    for child, resource_type in roots.items():
        root = {"id": f"/subscriptions/sub/resourceGroups/rg/providers/{resource_type}/root", "name": "root", "type": resource_type, "tags": {"E2E": "yes"}}
        monkeypatch.setattr(azure, "resolve_tagged_roots", lambda _: ("found", [root], ""))
        _child_sdk(monkeypatch, child)
        target = {"service": "azure_test", "resource_type": resource_type, "target_type": "tags", "target": {"E2E": "yes"}, "child": child}
        assert azure.resolve_tagged(target)[0] == "found"


def test_azure_lists_event_hub_entities_without_choosing_one(monkeypatch):
    root = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.EventHub/namespaces/ns",
        "name": "ns",
    }
    entity = {
        "id": f"{root['id']}/eventhubs/orders",
        "name": "orders",
        "type": "Microsoft.EventHub/namespaces/eventhubs",
    }
    event_hubs = SimpleNamespace(
        list_by_namespace=lambda *_: [SimpleNamespace(id=entity["id"], name=entity["name"])]
    )
    monkeypatch.setitem(__import__("sys").modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: "credential"))
    monkeypatch.setitem(
        __import__("sys").modules,
        "azure.mgmt.eventhub",
        SimpleNamespace(EventHubManagementClient=lambda *_: SimpleNamespace(event_hubs=event_hubs)),
    )

    result = azure.list_event_hub_entities(root, {"target": {"E2E": "yes"}})

    assert result == (
        "found", [{"id": entity["id"], "name": "orders"}], ""
    )


def _sdk(monkeypatch, module, **members):
    monkeypatch.setitem(__import__("sys").modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: "credential"))
    monkeypatch.setitem(__import__("sys").modules, module, SimpleNamespace(**members))


def _child_sdk(monkeypatch, child):
    if child == "instances":
        instances = SimpleNamespace(list=lambda *_: [SimpleNamespace(instance_id="0")])
        _sdk(monkeypatch, "azure.mgmt.compute", ComputeManagementClient=lambda *_: SimpleNamespace(virtual_machine_scale_set_vms=instances))
    elif child == "revisions":
        revisions = SimpleNamespace(list_revisions=lambda *_: [SimpleNamespace(name="revision")])
        _sdk(monkeypatch, "azure.mgmt.appcontainers", ContainerAppsAPIClient=lambda *_: SimpleNamespace(container_apps_revisions=revisions))
    elif child == "certificates":
        _sdk(monkeypatch, "azure.keyvault.certificates", CertificateClient=lambda *_: SimpleNamespace(list_properties_of_certificates=lambda: [SimpleNamespace(name="certificate")]))
    elif child == "secrets":
        _sdk(monkeypatch, "azure.keyvault.secrets", SecretClient=lambda *_: SimpleNamespace(list_properties_of_secrets=lambda: [SimpleNamespace(name="secret")]))
    else:
        rules = SimpleNamespace(list_by_server=lambda *_: [SimpleNamespace(name="rule")])
        _sdk(monkeypatch, "azure.mgmt.rdbms.postgresql_flexibleservers", PostgreSQLManagementClient=lambda *_: SimpleNamespace(firewall_rules=rules))
