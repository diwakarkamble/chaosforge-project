"""Interactive CLI session context."""


class PlatformContext:
    def __init__(self):
        self.cloud = None
        self.region = None
        self.azure_subscription = None
        self.azure_resource_group = None
        self.aks_cluster_name = None
        self.azure_location = None
        self.azure_account_name = None
        self.aks_kube_context = None
        self.cloud_identity = None
        self.timezone_id = None


context = PlatformContext()
