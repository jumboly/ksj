from ksj import __version__


def test_version_is_exported() -> None:
    assert isinstance(__version__, str)
    assert __version__.count(".") >= 2
