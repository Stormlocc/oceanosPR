"""External integration suites require explicit opt-ins."""


def pytest_addoption(parser):
    parser.addoption("--run-integration", action="store_true", default=False,
                     help="Collect integration tests that access the real STAC catalog")
    parser.addoption("--run-acolite", action="store_true", default=False,
                     help="Collect golden tests that execute the pinned local ACOLITE")


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: manually enabled tests requiring Internet")
    config.addinivalue_line("markers", "acolite: manually enabled tests requiring local ACOLITE")


def pytest_ignore_collect(collection_path, config):
    if collection_path.name == "integration" and not config.getoption("--run-integration"):
        return True
    if collection_path.name == "acolite_golden" and not config.getoption("--run-acolite"):
        return True
