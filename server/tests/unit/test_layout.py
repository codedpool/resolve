from pathlib import Path


def test_layout_files_exist():
    root = Path(__file__).resolve().parents[2]
    assert (root / "pyproject.toml").is_file()
    assert (root / "docker-compose.yml").is_file()
    assert (root / "alembic.ini").is_file()
    assert (root / "app").is_dir()
    assert (root / "scripts" / "check_secrets.py").is_file()
