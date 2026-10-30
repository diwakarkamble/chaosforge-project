from werkzeug.utils import secure_filename

from chaosforge.catalog import ExperimentCatalog


def load_metadata(service):
    """
    Load metadata.json for a supported service.
    """

    safe_service = secure_filename(service)

    if not safe_service:
        raise ValueError(f"Invalid service name: {service}")

    if "/" in safe_service or "\\" in safe_service or ".." in safe_service:
        raise ValueError(f"Invalid service path: {service}")

    if safe_service != service:
        return None

    return ExperimentCatalog().load_service(safe_service)
