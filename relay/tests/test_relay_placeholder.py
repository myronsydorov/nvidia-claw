from relay import __version__


def test_relay_package_importable() -> None:
    assert __version__ == "0.1.0"
