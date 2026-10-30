from chaosforge.interfaces.cli.interactive.ui.icons import (
    SERVICE_ICONS,
    STATUS_ICONS,
)


def test_service_icons():
    expected = {
        "lambda": "⚡",
        "dynamodb": "🗄",
        "elasticache": "🧠",
        "rds": "🛢",
        "sns": "📨",
        "ec2": "🖥",
        "fis": "🧪",
    }

    assert SERVICE_ICONS == expected


def test_status_icons():
    expected = {
        "SUCCESS": "🟢",
        "FAILED": "🔴",
        "PENDING": "🟡",
        "RUNNING": "🔵",
    }

    assert STATUS_ICONS == expected


def test_service_icons_keys():
    assert set(SERVICE_ICONS.keys()) == {
        "lambda",
        "dynamodb",
        "elasticache",
        "rds",
        "sns",
        "ec2",
        "fis",
    }


def test_status_icons_keys():
    assert set(STATUS_ICONS.keys()) == {
        "SUCCESS",
        "FAILED",
        "PENDING",
        "RUNNING",
    }
