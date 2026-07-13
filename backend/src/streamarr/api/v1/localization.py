"""Public localization discovery endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.database import get_db_session
from streamarr.services.settings import SettingsService

router = APIRouter()


class CultureInfo(BaseModel):
    name: str
    display_name: str
    english_name: str
    native_name: str
    two_letter_iso_language_name: str
    three_letter_iso_language_name: str


class CountryInfo(BaseModel):
    name: str
    display_name: str
    two_letter_iso_region_name: str
    three_letter_iso_region_name: str


class ParentalRatingInfo(BaseModel):
    name: str
    value: int
    country: str = "US"


class LocalizationOptions(BaseModel):
    default_locale: str
    supported_locales: list[str]
    cultures: list[CultureInfo]
    countries: list[CountryInfo]


SUPPORTED_CULTURES = [
    CultureInfo(
        name="en-US",
        display_name="English (United States)",
        english_name="English (United States)",
        native_name="English (United States)",
        two_letter_iso_language_name="en",
        three_letter_iso_language_name="eng",
    ),
    CultureInfo(
        name="de-DE",
        display_name="German (Germany)",
        english_name="German (Germany)",
        native_name="Deutsch (Deutschland)",
        two_letter_iso_language_name="de",
        three_letter_iso_language_name="deu",
    ),
]

SUPPORTED_COUNTRIES = [
    CountryInfo(
        name="United States",
        display_name="United States",
        two_letter_iso_region_name="US",
        three_letter_iso_region_name="USA",
    ),
    CountryInfo(
        name="Germany",
        display_name="Germany",
        two_letter_iso_region_name="DE",
        three_letter_iso_region_name="DEU",
    ),
]

SUPPORTED_PARENTAL_RATINGS = [
    ParentalRatingInfo(name="G", value=0),
    ParentalRatingInfo(name="PG", value=6),
    ParentalRatingInfo(name="PG-13", value=13),
    ParentalRatingInfo(name="R", value=17),
    ParentalRatingInfo(name="NC-17", value=18),
    ParentalRatingInfo(name="FSK 0", value=0, country="DE"),
    ParentalRatingInfo(name="FSK 6", value=6, country="DE"),
    ParentalRatingInfo(name="FSK 12", value=12, country="DE"),
    ParentalRatingInfo(name="FSK 16", value=16, country="DE"),
    ParentalRatingInfo(name="FSK 18", value=18, country="DE"),
]


async def _default_locale(session: AsyncSession) -> str:
    locale = await SettingsService(session).get("system.locale", "de-DE")
    if not isinstance(locale, str) or not locale:
        return "de-DE"
    return locale


@router.get("/options", response_model=LocalizationOptions)
async def get_localization_options(
    session: AsyncSession = Depends(get_db_session),
):
    """Return public localization options for clients."""
    return LocalizationOptions(
        default_locale=await _default_locale(session),
        supported_locales=[culture.name for culture in SUPPORTED_CULTURES],
        cultures=SUPPORTED_CULTURES,
        countries=SUPPORTED_COUNTRIES,
    )


@router.get("/cultures", response_model=list[CultureInfo])
async def get_localization_cultures():
    """Return supported UI cultures."""
    return SUPPORTED_CULTURES


@router.get("/countries", response_model=list[CountryInfo])
async def get_localization_countries():
    """Return supported countries/regions."""
    return SUPPORTED_COUNTRIES


@router.get("/parental-ratings", response_model=list[ParentalRatingInfo])
async def get_parental_ratings():
    """Return known parental/content ratings."""
    return SUPPORTED_PARENTAL_RATINGS

