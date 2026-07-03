import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from pyrate.api.dependencies import CurrentSuperuser, DatabaseSession
from pyrate.schemas.indexer import (
    IndexerCategoryCreate,
    IndexerCategoryRead,
    IndexerCreate,
    IndexerRead,
    IndexerUpdate,
    NewznabCapsResponse,
    NewznabCategory,
)
from pyrate.services.indexer_config import (
    IndexerService as IndexerConfigService,
)
from pyrate.utils.net import UnsafeUrlError, assert_safe_url

logger = logging.getLogger(__name__)

router = APIRouter()


class IndexerTypeInfo(BaseModel):
    """Information about an available indexer plugin type."""

    domain: str
    name: str
    description: str
    config_schema: dict


KNOWN_INDEXER_TYPES = [
    IndexerTypeInfo(
        domain="newznab",
        name="Newznab",
        description="Newznab-compatible Usenet indexer",
        config_schema={},
    ),
    IndexerTypeInfo(
        domain="torznab",
        name="Torznab",
        description="Torznab-compatible torrent indexer",
        config_schema={},
    ),
]


@router.get("/types", response_model=list[IndexerTypeInfo])
async def list_indexer_types(
    request: Request,
    current_user: CurrentSuperuser,
):
    """
    List available indexer types.

    Returns:
        List of available indexer types with their configuration schemas
    """
    return KNOWN_INDEXER_TYPES


@router.post("/validate", response_model=dict[str, Any])
async def validate_indexer_config(
    plugin_type: str,
    config: dict[str, Any],
    current_user: CurrentSuperuser,
):
    """
    Validate indexer configuration before saving.

    Args:
        plugin_type: Plugin domain (e.g., 'newznab', 'torznab')
        config: Configuration dictionary to validate

    Returns:
        Validation result with 'valid' (bool) and 'errors' (list)
    """
    valid_types = {"newznab", "torznab"}
    if plugin_type not in valid_types:
        return {"valid": False, "errors": [f"Unknown indexer type '{plugin_type}'"]}

    # Direct import and validation
    if plugin_type == "newznab":
        from pyrate.indexers.newznab import Newznab
        plugin_instance = Newznab(**config)
    else:
        from pyrate.indexers.torznab import Torznab
        plugin_instance = Torznab(**config)

    try:
        return await plugin_instance.validate_config(config)
    except Exception as e:
        logger.warning("Indexer validation failed for type=%s: %s", plugin_type, e)
        return {"valid": False, "errors": [f"Validation error: {str(e)}"]}
    finally:
        # Make sure the plugin's httpx client is released even if
        # ``validate_config`` raised.
        await plugin_instance.close()


@router.post("/caps", response_model=NewznabCapsResponse)
async def get_indexer_caps(
    current_user: CurrentSuperuser,
    host: str = Body(...),
    api_key: str = Body(...),
    ssl: bool = Body(False),
    verify_ssl: bool = Body(True),
    plugin_type: str = Body("newznab"),
):
    """
    Test connection to a Newznab/Torznab indexer and fetch available categories.
    Call this before saving the indexer to show the user what categories are available.
    """
    import httpx

    # Build base URL
    if host.startswith(("http://", "https://")):
        base_url = host.rstrip("/")
    else:
        protocol = "https" if ssl else "http"
        base_url = f"{protocol}://{host.rstrip('/')}"

    try:
        assert_safe_url(f"{base_url}/api")
        async with httpx.AsyncClient(verify=verify_ssl, timeout=15.0) as client:
            resp = await client.get(
                f"{base_url}/api",
                params={"t": "caps", "o": "json", "apikey": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return NewznabCapsResponse(connected=False, error="Connection timed out")
    except UnsafeUrlError as e:
        return NewznabCapsResponse(connected=False, error=str(e))
    except httpx.HTTPStatusError as e:
        return NewznabCapsResponse(
            connected=False,
            error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
        )
    except Exception as e:
        return NewznabCapsResponse(connected=False, error=str(e))

    # Parse categories from caps response
    def parse_categories(cats_data) -> list[NewznabCategory]:
        result = []
        if isinstance(cats_data, dict):
            cats_data = cats_data.get("category", [])
        if isinstance(cats_data, dict):
            cats_data = [cats_data]
        if not isinstance(cats_data, list):
            return result
        for cat in cats_data:
            attrs = cat.get("@attributes", cat)
            try:
                cat_id = int(attrs.get("id", 0))
                cat_name = str(attrs.get("name", ""))
            except (ValueError, TypeError):
                continue
            subcats_raw = cat.get("subcat", [])
            if isinstance(subcats_raw, dict):
                subcats_raw = [subcats_raw]
            subcats = []
            for sub in subcats_raw if isinstance(subcats_raw, list) else []:
                sub_attrs = sub.get("@attributes", sub)
                try:
                    subcats.append(
                        NewznabCategory(
                            id=int(sub_attrs.get("id", 0)),
                            name=str(sub_attrs.get("name", "")),
                        )
                    )
                except (ValueError, TypeError):
                    continue
            result.append(
                NewznabCategory(id=cat_id, name=cat_name, subcategories=subcats)
            )
        return result

    categories_raw = data.get("channel", {}).get("categories", {}) or data.get(
        "categories", {}
    )
    categories = parse_categories(categories_raw)

    return NewznabCapsResponse(connected=True, categories=categories)


@router.get("/{indexer_id}/categories", response_model=list[IndexerCategoryRead])
async def list_indexer_categories(
    indexer_id: str, db: DatabaseSession, current_user: CurrentSuperuser
):
    """Get all categories for an indexer."""
    service = IndexerConfigService(db)
    indexer = await service.get_by_id(indexer_id)
    if not indexer:
        raise HTTPException(status_code=404, detail="Indexer not found")
    return indexer.categories


@router.put("/{indexer_id}/categories", response_model=list[IndexerCategoryRead])
async def set_indexer_categories(
    indexer_id: str,
    categories: list[IndexerCategoryCreate],
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Replace all categories for an indexer."""
    service = IndexerConfigService(db)
    indexer = await service.get_model_by_id(indexer_id)
    if not indexer:
        raise HTTPException(status_code=404, detail="Indexer not found")
    result = await service.set_categories(indexer, categories)
    logger.info("Admin %s updated categories for indexer %s", current_user.guid, indexer_id)
    return result


@router.get("", response_model=list[IndexerRead])
async def list_indexers(db: DatabaseSession, current_user: CurrentSuperuser):
    service = IndexerConfigService(db)
    indexers = await service.get_all()
    return indexers


@router.get("/{indexer_id}", response_model=IndexerRead)
async def get_indexer(
    indexer_id: str, db: DatabaseSession, current_user: CurrentSuperuser
):
    service = IndexerConfigService(db)
    db_indexer = await service.get_by_id(indexer_id)
    return db_indexer


@router.put("/{indexer_id}", response_model=IndexerRead)
async def update_indexer(
    indexer_id: str,
    indexer_in: IndexerUpdate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    service = IndexerConfigService(db)
    db_indexer = await service.get_model_by_id(indexer_id)
    if db_indexer is None:
        raise HTTPException(status_code=404, detail="Indexer not found")
    result = await service.update(db_indexer, indexer_in)
    logger.info("Admin %s updated indexer %s", current_user.guid, indexer_id)
    return result


@router.post("", response_model=IndexerRead)
async def create_indexer(
    indexer_in: IndexerCreate, db: DatabaseSession, current_user: CurrentSuperuser
):
    service = IndexerConfigService(db)
    db_indexer = await service.create(indexer_in)
    logger.info("Admin %s created indexer %s", current_user.guid, db_indexer.guid)
    return db_indexer


@router.delete("/{indexer_id}", status_code=204)
async def delete_indexer(
    indexer_id: str, db: DatabaseSession, current_user: CurrentSuperuser
):
    service = IndexerConfigService(db)
    db_indexer = await service.get_model_by_id(indexer_id)
    if db_indexer is None:
        raise HTTPException(status_code=404, detail="Indexer not found")
    await service.delete(db_indexer)
    logger.info("Admin %s deleted indexer %s", current_user.guid, indexer_id)
