"""Package bootstrap tests."""

import oceanos


def test_package_is_importable() -> None:
    assert oceanos.__version__ == "0.1.0"

