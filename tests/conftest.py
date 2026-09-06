"""Live catalog tests require an explicit opt-in and are not collected by default."""


def pytest_addoption(parser):
    parser.addoption("--run-integration", action="store_true", default=False,
                     help="Collect integration tests that access the real STAC catalog")


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: manually enabled tests requiring Internet")


def pytest_ignore_collect(collection_path, config):
    if collection_path.name == "integration" and not config.getoption("--run-integration"):
        return True
