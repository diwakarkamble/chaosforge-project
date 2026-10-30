import json
import os


class FISCatalog:
    def __init__(self):

        catalog_path = os.path.join(
            os.path.dirname(__file__),
            "catalog.json",
        )

        with open(catalog_path, "r", encoding="utf-8-sig") as f:
            self.catalog = json.load(f)

    def get_services(self):

        return self.catalog["services"]

    def get_service(self, service_id):

        for service in self.catalog["services"]:
            if service["id"] == service_id:
                return service

        return None

    def get_experiments(self, service_id):

        service = self.get_service(service_id)

        if service:
            return service["experiments"]

        return []

    def get_experiment(self, service_id, experiment_id):

        experiments = self.get_experiments(service_id)

        for experiment in experiments:
            if experiment["id"] == experiment_id:
                return experiment

        return None

    def get_menu_items(self, service_id):

        menu = []

        experiments = self.get_experiments(service_id)

        for experiment in experiments:
            menu.append(
                {
                    "title": f"{experiment['name']} (AWS FIS)",
                    "experiment_id": experiment["id"],
                    "prefill": {
                        "service_id": service_id,
                        "experiment_id": experiment["id"],
                    },
                }
            )

        return menu
