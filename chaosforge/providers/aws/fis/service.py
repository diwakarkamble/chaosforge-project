import boto3


class FISService:
    def __init__(self, region="eu-central-1"):

        self.client = boto3.client("fis", region_name=region)

    # ---------------------------------------------------------
    # List Templates
    # ---------------------------------------------------------

    def list_templates(self):

        response = self.client.list_experiment_templates()

        templates = []

        for template in response.get("experimentTemplates", []):
            details = self.client.get_experiment_template(id=template["id"])

            tags = details.get("experimentTemplate", {}).get("tags", {})

            templates.append(
                {
                    "id": template["id"],
                    "description": template.get("description", ""),
                    "createdBy": tags.get("CreatedBy", "Unknown"),
                    "creationTime": template.get("creationTime"),
                }
            )

        return sorted(templates, key=lambda template: template["id"])

    # ---------------------------------------------------------
    # Delete Template
    # ---------------------------------------------------------

    def delete_template(self, template_id):

        self.client.delete_experiment_template(id=template_id)

        return True
