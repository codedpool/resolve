import resolve_workflows


def test_package_imports():
    assert resolve_workflows.__version__ == "0.1.0"
