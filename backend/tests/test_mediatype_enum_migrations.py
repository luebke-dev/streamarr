"""The PostgreSQL mediatype enum must know every type the plugins declare.

``MediaType`` is generated from the library plugin registry at import time, while
the database column uses a real PostgreSQL enum. Nothing connects the two: the
models build whatever the plugins say, and the test suite runs on SQLite, where
an unknown enum value is just a string. The two therefore drift apart silently,
and the failure surfaces as a 500 on every endpoint that queries an item type by
name:

    asyncpg.exceptions.InvalidTextRepresentationError:
    invalid input value for enum mediatype: "AUTHORS"

That is exactly what happened with ``AUTHORS``, the parent type the books plugin
declares: no migration ever added it, so ``/api/trailers``, ``/api/filters`` and
``/api/suggestions/autocomplete/typed`` failed for the web UI as well as for any
client. These tests read the migration directory and compare it against the
registry, which is the only place the gap is visible without a database.
"""

import re
from pathlib import Path

import pytest

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"

# `ALTER TYPE mediatype ADD VALUE IF NOT EXISTS 'X'` - only this enum; other
# enums (listtype, markertype, ...) have their own values and must not count as
# coverage.
ADD_VALUE = re.compile(
    r"ALTER\s+TYPE\s+mediatype\s+ADD\s+VALUE\s+IF\s+NOT\s+EXISTS\s+['\"]([A-Z_]+)['\"]",
    re.I,
)
# Migrations may also hold the values in a list and loop over them.
NEW_VALUES = re.compile(r"NEW_VALUES\s*=\s*\[([^\]]*)\]", re.S)
QUOTED = re.compile(r"['\"]([A-Z_]+)['\"]")
# The enum as PostgreSQL was first told about it.
CREATE_ENUM = re.compile(r"sa\.Enum\(([^)]*?)name=['\"]mediatype['\"]", re.S)


def _migration_files() -> list[Path]:
    files = sorted(VERSIONS_DIR.glob("*.py"))
    assert files, f"no migrations found in {VERSIONS_DIR}"
    return files


def _enum_values_in_migrations() -> set[str]:
    values: set[str] = set()
    for path in _migration_files():
        text = path.read_text()
        values.update(v.upper() for v in ADD_VALUE.findall(text))
        for block in NEW_VALUES.findall(text):
            values.update(v.upper() for v in QUOTED.findall(block))
        for block in CREATE_ENUM.findall(text):
            values.update(v.upper() for v in QUOTED.findall(block))
    return values


def test_every_plugin_media_type_reaches_the_database_enum():
    from streamarr.libraries import get_all_media_item_types

    declared = {item.upper() for item in get_all_media_item_types()}
    migrated = _enum_values_in_migrations()

    assert declared <= migrated, (
        "these media types are declared by plugins but no migration adds them to "
        f"the PostgreSQL enum: {sorted(declared - migrated)}"
    )


def test_authors_is_covered():
    """The regression this file exists for."""
    assert "AUTHORS" in _enum_values_in_migrations()


def test_the_migration_chain_has_exactly_one_head():
    """Two heads means a migration was written without wiring it in.

    Alembic answers this itself; re-implementing the graph walk in a regex would
    only be a worse copy of it.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = VERSIONS_DIR.parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(VERSIONS_DIR.parent))

    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"expected one head, found {heads}"


@pytest.mark.parametrize("value", ["MOVIES", "SHOWS", "BOOKS", "AUTHORS"])
def test_the_core_types_stay_covered(value):
    """A migration rewrite must not drop values earlier ones added."""
    assert value in _enum_values_in_migrations()
