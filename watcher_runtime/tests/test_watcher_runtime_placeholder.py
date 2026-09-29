from watcher_runtime import __version__


def test_watcher_runtime_package_importable() -> None:
    assert __version__ == "0.1.0"
