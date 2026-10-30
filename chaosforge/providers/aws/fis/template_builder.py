import uuid

import boto3


class FISTemplateBuilder:
    """
    Builds an AWS FIS Experiment Template.
    """

    def build(
        self,
        service,
        experiment,
        experiment_name,
        description,
        target_arn,
        role_arn,
        parameters,
        region=None,
        created_by=None,
    ):

        action = self._build_action(
            experiment,
            parameters,
        )

        target = self._build_target(
            service,
            experiment,
            target_arn,
            parameters,
            region,
        )

        return {
            "description": description,
            "roleArn": role_arn,
            "stopConditions": [{"source": "none"}],
            "targets": {"Target1": target},
            "actions": {"Action1": action},
            "tags": {
                "CreatedBy": created_by or "ChaosForge",
                "Experiment": experiment_name,
                "Id": str(uuid.uuid4()),
            },
        }

    def _build_target(
        self,
        service,
        experiment,
        target_arn,
        parameters,
        region,
    ):

        default_resource_types = {
            "lambda": "aws:lambda:function",
            "dynamodb": "aws:dynamodb:table",
            "rds": "aws:rds:db",
            "ec2": "aws:ec2:instance",
            "elasticache": "aws:elasticache:replicationgroup",
            "ecs": "aws:ecs:service",
            "s3": "aws:s3:bucket",
        }

        resource_type = experiment.get("resource_type")

        if not resource_type:
            service_id = service["id"]

            if service_id not in default_resource_types:
                raise ValueError(f"Unsupported FIS service: {service_id}")

            resource_type = default_resource_types[service_id]

        #
        # Amazon S3
        # Uses Resource Tags instead of ARNs
        #

        if service["id"] == "s3":
            tag_key = parameters.get(
                "tag_key",
                "Name",
            )

            tag_value = parameters.get(
                "tag_value",
                "",
            ).strip()

            if not tag_value:
                raise ValueError(
                    "Resource Tag Value is required for S3 FIS experiments."
                )

            return {
                "resourceType": resource_type,
                "resourceTags": {
                    tag_key: tag_value,
                },
                "selectionMode": "ALL",
            }

        if service["id"] == "elasticache" and resource_type == "aws:elasticache:replicationgroup":
            tags = boto3.client("elasticache", region_name=region).list_tags_for_resource(
                ResourceName=target_arn
            ).get("TagList", [])
            resource_tags = {tag["Key"]: tag["Value"] for tag in tags}
            if not resource_tags:
                raise ValueError("ElastiCache FIS targets must have at least one resource tag.")

            target_parameters = {}
            for parameter in experiment.get("parameters", []):
                if not parameter.get("target_parameter"):
                    continue
                name = parameter["name"]
                value = parameters.get(name)
                if value is None or str(value).strip() == "":
                    if parameter.get("required", True):
                        raise ValueError(f"Target parameter '{name}' is required for ElastiCache FIS.")
                    continue
                target_parameters[parameter.get("aws_name", name)] = str(value)

            target = {
                "resourceType": resource_type,
                "resourceTags": resource_tags,
                "selectionMode": "ALL",
            }
            if target_parameters:
                target["parameters"] = target_parameters
            return target

        #
        # EC2
        #
        # ChaosForge resource selection returns an EC2
        # instance ID such as:
        #
        #     i-0267f34384640b8b5
        #
        # AWS FIS requires an ARN:
        #
        #     arn:aws:ec2:<region>:<account>:instance/<id>
        #
        # If an ARN is already supplied, preserve it.
        #

        if service["id"] == "ec2" and resource_type == "aws:ec2:instance":
            target_arn = self._normalize_ec2_target(
                target_arn,
                region,
            )

        #
        # Default for all other AWS services
        #

        return {
            "resourceType": resource_type,
            "resourceArns": [target_arn],
            "selectionMode": "ALL",
        }

    def _normalize_ec2_target(
        self,
        target,
        region,
    ):
        """
        Convert an EC2 instance ID into an EC2 instance ARN.

        Accepts either:

            i-xxxxxxxxxxxxxxxxx

        or:

            arn:aws:ec2:<region>:<account>:instance/i-xxxxxxxxxxxxxxxxx

        Already valid ARNs are returned unchanged.
        """

        if not target:
            raise ValueError("EC2 target instance ID is required.")

        target = str(target).strip()

        #
        # Already an ARN
        #

        if target.startswith("arn:"):
            return target

        #
        # EC2 instance ID
        #

        if not target.startswith("i-"):
            raise ValueError(
                f"Invalid EC2 instance target '{target}'. "
                "Expected an EC2 instance ID or ARN."
            )

        sts_client = boto3.client(
            "sts",
            region_name=region,
        )

        account_id = sts_client.get_caller_identity()["Account"]

        return f"arn:aws:ec2:{region}:{account_id}:instance/{target}"

    def _build_action(
        self,
        experiment,
        parameters,
    ):

        action_parameters = {}

        parameter_lookup = {
            parameter["name"]: parameter
            for parameter in experiment.get(
                "parameters",
                [],
            )
        }

        for key, value in parameters.items():
            #
            # Skip empty optional parameters
            #

            if value is None or str(value).strip() == "":
                continue

            #
            # These belong to Target, not Action
            #

            if key in [
                "tag_key",
                "tag_value",
            ]:
                continue

            parameter = parameter_lookup.get(key)

            if parameter and parameter.get("target_parameter"):
                continue

            if parameter:
                aws_name = parameter.get(
                    "aws_name",
                    key,
                )
            else:
                aws_name = key

            if isinstance(value, bool):
                action_parameters[aws_name] = str(value).lower()
            else:
                action_parameters[aws_name] = str(value)

        target_key = experiment.get("target_key")

        if not target_key:
            raise ValueError(
                f"Missing 'target_key' for experiment '{experiment['id']}'"
            )

        return {
            "actionId": experiment["fis_action"],
            "description": "Generated by ChaosForge",
            "parameters": action_parameters,
            "targets": {
                target_key: "Target1",
            },
        }
