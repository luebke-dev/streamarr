"""Pydantic schemas for release quality scoring configuration."""

from pydantic import BaseModel, Field


class ResolutionWeights(BaseModel):
    """Scoring weights for video resolution."""

    p2160: int = Field(default=25, ge=0, le=100, alias="2160p")
    p4320: int = Field(default=25, ge=0, le=100, alias="4320p")
    p1080: int = Field(default=20, ge=0, le=100, alias="1080p")
    p720: int = Field(default=10, ge=0, le=100, alias="720p")
    p480: int = Field(default=5, ge=0, le=100, alias="480p")

    model_config = {"populate_by_name": True}


class ShowResolutionWeights(BaseModel):
    """Scoring weights for video resolution (shows - prefers 1080p more)."""

    p2160: int = Field(default=25, ge=0, le=100, alias="2160p")
    p1080: int = Field(default=22, ge=0, le=100, alias="1080p")
    p720: int = Field(default=15, ge=0, le=100, alias="720p")
    p480: int = Field(default=8, ge=0, le=100, alias="480p")

    model_config = {"populate_by_name": True}


class MovieSourceWeights(BaseModel):
    """Scoring weights for release sources (movies)."""

    bluray: int = Field(default=20, ge=0, le=100)
    remux: int = Field(default=20, ge=0, le=100)
    web_dl: int = Field(default=15, ge=0, le=100, alias="web-dl")
    webrip: int = Field(default=12, ge=0, le=100)
    hdtv: int = Field(default=8, ge=0, le=100)
    dvd: int = Field(default=5, ge=0, le=100)
    screener: int = Field(default=2, ge=0, le=100)
    cam: int = Field(default=1, ge=0, le=100)

    model_config = {"populate_by_name": True}


class ShowSourceWeights(BaseModel):
    """Scoring weights for release sources (shows - WEB-DL preferred)."""

    web_dl: int = Field(default=20, ge=0, le=100, alias="web-dl")
    webrip: int = Field(default=18, ge=0, le=100)
    bluray: int = Field(default=16, ge=0, le=100)
    remux: int = Field(default=16, ge=0, le=100)
    hdtv: int = Field(default=12, ge=0, le=100)
    dvd: int = Field(default=5, ge=0, le=100)
    screener: int = Field(default=2, ge=0, le=100)
    cam: int = Field(default=1, ge=0, le=100)

    model_config = {"populate_by_name": True}


class CodecWeights(BaseModel):
    """Scoring weights for video codecs."""

    h265: int = Field(default=15, ge=0, le=100)
    av1: int = Field(default=15, ge=0, le=100)
    h264: int = Field(default=12, ge=0, le=100)
    xvid: int = Field(default=5, ge=0, le=100)
    divx: int = Field(default=5, ge=0, le=100)


class ShowCodecWeights(BaseModel):
    """Scoring weights for video codecs (shows)."""

    h265: int = Field(default=15, ge=0, le=100)
    av1: int = Field(default=15, ge=0, le=100)
    h264: int = Field(default=13, ge=0, le=100)
    xvid: int = Field(default=5, ge=0, le=100)
    divx: int = Field(default=5, ge=0, le=100)


class AudioWeights(BaseModel):
    """Scoring weights for audio codecs."""

    truehd: int = Field(default=10, ge=0, le=100)
    dts_hd: int = Field(default=10, ge=0, le=100, alias="dts-hd")
    atmos: int = Field(default=10, ge=0, le=100)
    dts: int = Field(default=8, ge=0, le=100)
    eac3: int = Field(default=6, ge=0, le=100)
    ac3: int = Field(default=6, ge=0, le=100)
    aac: int = Field(default=4, ge=0, le=100)

    model_config = {"populate_by_name": True}


class ShowAudioWeights(BaseModel):
    """Scoring weights for audio codecs (shows - slightly higher AAC/AC3)."""

    truehd: int = Field(default=10, ge=0, le=100)
    dts_hd: int = Field(default=10, ge=0, le=100, alias="dts-hd")
    atmos: int = Field(default=10, ge=0, le=100)
    dts: int = Field(default=8, ge=0, le=100)
    eac3: int = Field(default=7, ge=0, le=100)
    ac3: int = Field(default=7, ge=0, le=100)
    aac: int = Field(default=5, ge=0, le=100)

    model_config = {"populate_by_name": True}


class MovieScoringConfig(BaseModel):
    """Full scoring configuration for movie releases."""

    resolution: ResolutionWeights = Field(default_factory=ResolutionWeights)
    source: MovieSourceWeights = Field(default_factory=MovieSourceWeights)
    codec: CodecWeights = Field(default_factory=CodecWeights)
    audio: AudioWeights = Field(default_factory=AudioWeights)

    # Bonus points for special features
    hdr_bonus: int = Field(default=5, ge=0, le=100)
    dolby_vision_bonus: int = Field(default=5, ge=0, le=100)
    remux_bonus: int = Field(default=3, ge=0, le=100)
    proper_bonus: int = Field(default=5, ge=0, le=100)
    repack_bonus: int = Field(default=3, ge=0, le=100)
    trusted_group_bonus: int = Field(default=5, ge=0, le=100)

    # Language scoring
    language_match_bonus: int = Field(default=10, ge=0, le=100)
    language_mismatch_penalty: int = Field(default=0, ge=0, le=100)

    # Release group lists
    trusted_groups: list[str] = Field(
        default=[
            "SPARKS",
            "DEFLATE",
            "TOMMY",
            "VYNDROS",
            "SiC",
            "DON",
            "CRUELTY",
            "SCENE",
            "ROVERS",
            "SURCODE",
            "FLUX",
            "NCmt",
        ]
    )
    blocked_groups: list[str] = Field(default=[])


class ShowScoringConfig(BaseModel):
    """Full scoring configuration for TV show releases."""

    resolution: ShowResolutionWeights = Field(default_factory=ShowResolutionWeights)
    source: ShowSourceWeights = Field(default_factory=ShowSourceWeights)
    codec: ShowCodecWeights = Field(default_factory=ShowCodecWeights)
    audio: ShowAudioWeights = Field(default_factory=ShowAudioWeights)

    # Bonus points for special features
    hdr_bonus: int = Field(default=5, ge=0, le=100)
    dolby_vision_bonus: int = Field(default=5, ge=0, le=100)
    proper_bonus: int = Field(default=5, ge=0, le=100)
    repack_bonus: int = Field(default=3, ge=0, le=100)
    trusted_group_bonus: int = Field(default=5, ge=0, le=100)

    # Language scoring
    language_match_bonus: int = Field(default=10, ge=0, le=100)
    language_mismatch_penalty: int = Field(default=0, ge=0, le=100)

    # Release group lists
    trusted_groups: list[str] = Field(
        default=[
            "DEFLATE",
            "TOMMY",
            "FLUX",
            "NTb",
            "CAKES",
            "WELP",
            "SIGMA",
            "BTN",
            "CRUELTY",
            "HONE",
            "CMRG",
            "TMSF",
            "AVTOMAT",
            "iSSEYMiYAKE",
        ]
    )
    blocked_groups: list[str] = Field(default=[])


# --------------------------------------------------------------------------- #
# Sonarr/Radarr-style quality profile (ordered allowed list + cutoff).
# The legacy additive *ScoringConfig above is kept and reused as the
# *within-rung* tiebreaker via QualityProfile.scoring.
# --------------------------------------------------------------------------- #


class QualityItem(BaseModel):
    """One rung of a profile's ordered quality list.

    ``id`` is a canonical ladder rung id (see ``libraries/quality.py``).
    Order in ``QualityProfile.items`` is lowest -> highest (profile rank).
    """

    id: str
    allowed: bool = True


class QualityProfile(BaseModel):
    """Ordered allowed-quality list + cutoff for one media type.

    Stored as JSON under settings keys ``quality.profile.{type}`` and
    (optionally) ``quality.profile.favorites.{type}``.
    """

    name: str = "default"
    # lowest -> highest; only ``allowed`` rungs are eligible. Rungs absent
    # from this list are treated as not-allowed.
    items: list[QualityItem] = Field(default_factory=list)
    # rung id at which quality is "good enough" (upgrades stop here).
    cutoff: str | None = None
    upgrade_allowed: bool = True
    # Optional additive within-rung tiebreaker. Shape matches the legacy
    # MovieScoringConfig/ShowScoringConfig (free-form so all media kinds
    # can carry their own weights); None -> plugin defaults.
    scoring: dict | None = None

    model_config = {"populate_by_name": True}
