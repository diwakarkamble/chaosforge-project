from chaosforge.application.services.campaign_yaml import CampaignYAMLService


def build_campaign(data):
    return CampaignYAMLService().build_document(data)
