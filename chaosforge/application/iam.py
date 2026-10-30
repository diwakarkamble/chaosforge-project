"""Shared IAM action extraction for CLI and Web policy displays."""

IAM_CATEGORIES = ("read", "modify", "delete", "additional")


def iam_actions(metadata):
    iam = metadata.get("iam", {})
    return sorted(
        {
            action
            for category in IAM_CATEGORIES
            for action in iam.get(category, [])
        }
    )
