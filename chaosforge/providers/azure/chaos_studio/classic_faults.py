"""Verified Azure Chaos Studio classic service-direct fault contracts."""

import json

CLASSIC_FAULTS = {
    ("azure_vm", "azure-vm-redeploy"): ("urn:csci:microsoft:virtualMachine:redeploy/1.0", "Microsoft-VirtualMachine", "Virtual Machine Contributor"),
    ("azure_vm", "azure-vm-shutdown"): ("urn:csci:microsoft:virtualMachine:shutdown/1.0", "Microsoft-VirtualMachine", "Virtual Machine Contributor"),
    ("azure_vmss", "azure-vmss-shutdown"): ("urn:csci:microsoft:virtualMachineScaleSet:shutdown/1.0", "Microsoft-VirtualMachineScaleSet", "Virtual Machine Contributor"),
    ("azure_vmss", "azure-vmss-shutdown-2-0"): ("urn:csci:microsoft:virtualMachineScaleSet:shutdown/2.0", "Microsoft-VirtualMachineScaleSet", "Virtual Machine Contributor"),
    ("azure_functions", "azure-functions-stop-app-service"): ("urn:csci:microsoft:appService:stop/1.0", "Microsoft-AppService", "Website Contributor"),
    ("azure_key_vault", "azure-key-vault-deny-access"): ("urn:csci:microsoft:keyVault:denyAccess/1.0", "Microsoft-KeyVault", "Key Vault Certificates Officer"),
    ("azure_key_vault", "azure-key-vault-disable-certificate"): ("urn:csci:microsoft:keyvault:disableCertificate/1.0", "Microsoft-KeyVault", "Key Vault Certificates Officer"),
    ("azure_key_vault", "azure-key-vault-increment-certificate-version"): ("urn:csci:microsoft:keyvault:incrementCertificateVersion/1.0", "Microsoft-KeyVault", "Key Vault Certificates Officer"),
    ("azure_key_vault", "azure-key-vault-update-certificate-policy"): ("urn:csci:microsoft:keyvault:updateCertificatePolicy/1.0", "Microsoft-KeyVault", "Key Vault Certificates Officer"),
    ("azure_cosmos_db", "azure-cosmos-db-failover"): ("urn:csci:microsoft:cosmosDB:failover/1.0", "Microsoft-CosmosDB", "Cosmos DB Operator"),
}


def fault_details(service, experiment_id):
    try:
        return CLASSIC_FAULTS[(service, experiment_id)]
    except KeyError:
        raise ValueError(f"Unsupported Azure Chaos Studio classic experiment: {service}/{experiment_id}.") from None


def action_parameters(service, experiment_id, variables):
    """Translate interface values to the documented classic fault parameter names."""
    values = dict(variables)
    if experiment_id in {"azure-vm-shutdown", "azure-vmss-shutdown", "azure-vmss-shutdown-2-0"}:
        parameters = {"abruptShutdown": values.get("abrupt_shutdown", False)}
        if experiment_id == "azure-vmss-shutdown":
            try:
                instances = json.loads(values["instances"])
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Instance IDs must be a JSON array, for example [\"0\", \"1\"].") from exc
            if not isinstance(instances, list) or not instances or any(
                isinstance(instance, bool) or not str(instance).isdigit() for instance in instances
            ):
                raise ValueError("Instance IDs must be a non-empty JSON array of VM scale set instance IDs.")
            parameters["instances"] = json.dumps([str(instance) for instance in instances])
        return parameters
    if experiment_id == "azure-cosmos-db-failover":
        return {"readRegion": values["read_region"]}
    if experiment_id == "azure-key-vault-disable-certificate":
        return {"certificateName": values["certificate_name"]}
    if experiment_id == "azure-key-vault-increment-certificate-version":
        return {"certificateName": values["certificate_name"]}
    if experiment_id == "azure-key-vault-update-certificate-policy":
        return {"certificateName": values["certificate_name"], "enabled": values["enabled"]}
    return {}
