from chaosforge.application.services.generic import add_generic


def execute_experiment(experiment_id, prefill=None):

    #
    # Azure AKS
    #

    if experiment_id.startswith("aks-"):
        from chaosforge.interfaces.cli.interactive.azure_aks_service import (
            add_aks_experiment,
        )
        add_aks_experiment(experiment_id)
        return

    if experiment_id.startswith("azure-redis-"):
        add_generic("azure_redis", experiment_id, prefill)
        return


    #
    # Lambda
    #

    if experiment_id.startswith("lambda-"):
        add_generic("lambda", experiment_id, prefill)

        return

    #
    # DynamoDB
    #

    if experiment_id.startswith("dynamodb-"):
        add_generic("dynamodb", experiment_id, prefill)

        return

    #
    # RDS
    #

    if experiment_id.startswith("rds-"):
        add_generic("rds", experiment_id, prefill)

        return

    #
    # ElastiCache
    #

    if experiment_id.startswith("elasticache-"):
        add_generic("elasticache", experiment_id, prefill)

        return

    #
    # API Gateway
    #

    if experiment_id.startswith("apigateway-"):
        add_generic("apigateway", experiment_id, prefill)

        return

    #
    # SNS
    #

    if experiment_id.startswith("sns-"):
        add_generic("sns", experiment_id, prefill)

        return

    #
    # VPC
    #

    if experiment_id.startswith("vpc-"):
        add_generic("vpc", experiment_id, prefill)

        return

    #
    # ECS
    #

    if experiment_id.startswith("ecs-"):
        add_generic("ecs", experiment_id, prefill)

        return

    #
    # S3
    #

    if experiment_id.startswith("s3-"):
        add_generic("s3", experiment_id, prefill)

        return

    #
    # EC2
    #

    if experiment_id.startswith("ec2-"):
        add_generic("ec2", experiment_id, prefill)

        return

    #
    # ELB
    #

    if experiment_id.startswith("elb-"):
        add_generic("elb", experiment_id, prefill)

        return

    #
    # EKS
    #
    if experiment_id.startswith("eks-"):
        add_generic("eks", experiment_id, prefill)

        return

    #
    # Chaos Mesh
    #

    if experiment_id.startswith("chaos-mesh-"):
        add_generic("chaos_mesh", experiment_id, prefill)
        return

    #
    # AWS FIS
    #

    if experiment_id.startswith("fis-"):
        add_generic("fis", experiment_id, prefill)

        return

    print(f"\nUnknown experiment : {experiment_id}")

    input("\nPress Enter...")
