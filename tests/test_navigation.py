import pytest

from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu


def test_back_to_main_menu_is_exception():
    assert issubclass(BackToMainMenu, Exception)


def test_raise_back_to_main_menu():
    with pytest.raises(BackToMainMenu):
        raise BackToMainMenu()


def test_exception_message():
    with pytest.raises(BackToMainMenu, match="Return to main menu"):
        raise BackToMainMenu("Return to main menu")
