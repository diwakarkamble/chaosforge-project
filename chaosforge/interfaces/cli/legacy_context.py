class PlatformContext:
    def __init__(self):
        self.cloud = None
        self.region = None

        # Azure / AKS
        self.azure_subscription = None
        self.azure_resource_group = None
        self.aks_cluster_name = None
        self.azure_location = None       # cluster region e.g. "germanywestcentral"
        self.azure_account_name = None   # subscription display name
        self.aks_kube_context = None     # confirmed kubeconfig context name


context = PlatformContext()
