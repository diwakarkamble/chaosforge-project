"""Azure built-in role sufficiency for ChaosForge capability checks."""

AZURE_BUILT_IN_ROLE_DEFINITION_IDS = {
    "Contributor": "b24988ac-6180-42a0-ab88-20f7382dd24c",
    "Cosmos DB Operator": "230815da-be43-4aae-9cb4-875f7bd000aa",
    "Event Hubs Data Owner": "f526a384-b230-433a-b45c-95f59c4a2dec",
    "Key Vault Administrator": "00482a5a-887f-4fb3-b363-3b7fe8e74483",
    "Key Vault Certificates Officer": "a4417e6f-fecd-4de8-b567-7b0420556985",
    "Owner": "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
    "Redis Cache Contributor": "e0f68234-74aa-48ed-b826-c38b57376e17",
    "Virtual Machine Contributor": "9980e02c-c2be-4d73-94e8-173b1dc7c5b",
    "Website Contributor": "de139f84-1756-47ae-9be6-808fbbe84772",
}

_MANAGEMENT_ROLES = {
    "Cosmos DB Operator",
    "Redis Cache Contributor",
    "Virtual Machine Contributor",
    "Website Contributor",
}

_DATA_PLANE_ALTERNATIVES = {
    "Key Vault Certificates Officer": {"Key Vault Administrator"},
}


def accepted_role_definition_ids(required_role):
    """Return built-in role IDs that safely satisfy one required capability."""
    try:
        accepted = {AZURE_BUILT_IN_ROLE_DEFINITION_IDS[required_role]}
    except KeyError:
        raise ValueError(f"Unsupported Azure target role: {required_role}.") from None
    if required_role in _MANAGEMENT_ROLES:
        accepted.update(
            {
                AZURE_BUILT_IN_ROLE_DEFINITION_IDS["Contributor"],
                AZURE_BUILT_IN_ROLE_DEFINITION_IDS["Owner"],
            }
        )
    for alternative in _DATA_PLANE_ALTERNATIVES.get(required_role, set()):
        accepted.add(AZURE_BUILT_IN_ROLE_DEFINITION_IDS[alternative])
    return {role_id.lower() for role_id in accepted}


def accepted_role_names(required_role):
    """Return a display-safe description of roles that satisfy a capability."""
    if required_role in _MANAGEMENT_ROLES:
        return f"{required_role}, Contributor, or Owner"
    alternatives = sorted(_DATA_PLANE_ALTERNATIVES.get(required_role, set()))
    return ", ".join([required_role, *alternatives])


def assignment_satisfies(assignment, principal_id, accepted_role_ids):
    """Confirm an assignment belongs to the selected UAMI and grants a valid role."""
    assignment_principal = getattr(assignment, "principal_id", None)
    return (
        any(
            str(getattr(assignment, "role_definition_id", "") or "")
            .lower()
            .endswith(role_id)
            for role_id in accepted_role_ids
        )
        and (
            not assignment_principal
            or str(assignment_principal).lower() == str(principal_id).lower()
        )
    )
