"""Compatibility facade for AKS Chaos Studio extended checks.

Implementation lives in cohesive modules. This facade retains the historical
import path and private helper patch seam used by downstream tests.
"""

from . import _extended_cluster_plane as _cluster_plane
from . import _extended_common as _common
from . import _extended_dns as _dns
from . import _extended_http as _http
from . import _extended_io as _io
from . import _extended_time as _time

TIME_CHAOS_IDS = _common.TIME_CHAOS_IDS
HTTP_CHAOS_IDS = _common.HTTP_CHAOS_IDS
DNS_CHAOS_IDS = _common.DNS_CHAOS_IDS
IO_CHAOS_IDS = _common.IO_CHAOS_IDS
CLUSTER_PLANE_CHAOS_IDS = _common.CLUSTER_PLANE_CHAOS_IDS

_kubectl = _common._kubectl
_check_chaos_crd = _common._check_chaos_crd
_check_no_stale_chaos_crd = _common._check_no_stale_chaos_crd
_get_pods_json = _common._get_pods_json
_get_deployment_json = _common._get_deployment_json
_first_running_pod = _common._first_running_pod
_get_workload_by_selector = _common._get_workload_by_selector
_get_ready_node_count = _common._get_ready_node_count
_canary_pod = _common._canary_pod
_parse_duration_to_secs = _common._parse_duration_to_secs
_parse_skew_offset_to_secs = _common._parse_skew_offset_to_secs


def _sync_helpers(module):
    """Make facade helper patches visible to extracted implementation modules."""
    for name in (
        "_kubectl", "_check_chaos_crd", "_check_no_stale_chaos_crd",
        "_get_pods_json", "_get_deployment_json", "_first_running_pod",
        "_get_workload_by_selector", "_get_ready_node_count",
        "_canary_pod", "_parse_duration_to_secs", "_parse_skew_offset_to_secs",
    ):
        setattr(_common, name, globals()[name])
        if hasattr(module, name):
            setattr(module, name, globals()[name])


def _common_helper(helper):
    def wrapped(*args, **kwargs):
        _sync_helpers(_common)
        return helper(*args, **kwargs)
    return wrapped


def _synced_checks(module, checks):
    """Keep helper monkeypatches effective after a builder has returned checks."""
    def sync_check(check):
        def wrapped():
            _sync_helpers(module)
            return check()
        return wrapped
    return {label: sync_check(check) for label, check in checks.items()}


_check_chaos_crd = _common_helper(_common._check_chaos_crd)
_check_no_stale_chaos_crd = _common_helper(_common._check_no_stale_chaos_crd)
_get_pods_json = _common_helper(_common._get_pods_json)
_get_deployment_json = _common_helper(_common._get_deployment_json)
_first_running_pod = _common_helper(_common._first_running_pod)
_get_workload_by_selector = _common_helper(_common._get_workload_by_selector)
_get_ready_node_count = _common_helper(_common._get_ready_node_count)
_canary_pod = _common_helper(_common._canary_pod)


def build_time_chaos_pre_checks(*args, **kwargs):
    _sync_helpers(_time)
    return _synced_checks(_time, _time.build_time_chaos_pre_checks(*args, **kwargs))


def build_time_chaos_post_checks(*args, **kwargs):
    _sync_helpers(_time)
    return _synced_checks(_time, _time.build_time_chaos_post_checks(*args, **kwargs))


def build_http_chaos_pre_checks(*args, **kwargs):
    _sync_helpers(_http)
    return _synced_checks(_http, _http.build_http_chaos_pre_checks(*args, **kwargs))


def build_http_chaos_post_checks(*args, **kwargs):
    _sync_helpers(_http)
    return _synced_checks(_http, _http.build_http_chaos_post_checks(*args, **kwargs))


def build_dns_chaos_pre_checks(*args, **kwargs):
    _sync_helpers(_dns)
    return _synced_checks(_dns, _dns.build_dns_chaos_pre_checks(*args, **kwargs))


def build_dns_chaos_post_checks(*args, **kwargs):
    _sync_helpers(_dns)
    return _synced_checks(_dns, _dns.build_dns_chaos_post_checks(*args, **kwargs))


def build_cluster_plane_chaos_pre_checks(*args, **kwargs):
    _sync_helpers(_cluster_plane)
    return _synced_checks(_cluster_plane, _cluster_plane.build_cluster_plane_chaos_pre_checks(*args, **kwargs))


def build_cluster_plane_chaos_post_checks(*args, **kwargs):
    _sync_helpers(_cluster_plane)
    return _synced_checks(_cluster_plane, _cluster_plane.build_cluster_plane_chaos_post_checks(*args, **kwargs))


def build_io_chaos_pre_checks(*args, **kwargs):
    _sync_helpers(_io)
    return _synced_checks(_io, _io.build_io_chaos_pre_checks(*args, **kwargs))


def build_io_chaos_post_checks(*args, **kwargs):
    _sync_helpers(_io)
    return _synced_checks(_io, _io.build_io_chaos_post_checks(*args, **kwargs))
