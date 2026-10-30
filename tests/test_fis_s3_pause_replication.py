from chaosforge.application.component_fis import bind_component_fis
from chaosforge.interfaces.web.forms import normalize_values
from chaosforge.providers.aws.fis.catalog import FISCatalog
from chaosforge.providers.aws.fis.template_builder import FISTemplateBuilder


def test_s3_pause_replication_destination_buckets_is_optional_in_bound_forms():
    metadata = bind_component_fis(
        {"inputs": []}, "s3", "pause-replication"
    )
    destination = next(
        field
        for field in metadata["inputs"]
        if field["name"] == "destination_buckets"
    )

    assert destination["required"] is False
    assert normalize_values(
        [destination], {"destination_buckets": ""}
    ) == ({"destination_buckets": ""}, {})


def test_s3_pause_replication_omits_blank_destination_buckets_from_fis_action():
    experiment = FISCatalog().get_experiment("s3", "pause-replication")

    action = FISTemplateBuilder()._build_action(
        experiment,
        {
            "tag_key": "Name",
            "tag_value": "source-bucket",
            "region": "eu-west-1",
            "duration": "PT5M",
            "destination_buckets": "",
        },
    )

    assert action["parameters"] == {
        "region": "eu-west-1",
        "duration": "PT5M",
    }
