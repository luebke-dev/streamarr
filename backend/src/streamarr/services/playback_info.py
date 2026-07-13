"""Playback-info response orchestration."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from streamarr.models.device import Device
from streamarr.models.media import MediaFile
from streamarr.services.media import MediaService
from streamarr.services.media_access import require_media_play_access
from streamarr.services.playback_decision import (
    PlaybackDecisionError,
    PlaybackDecisionService,
)
from streamarr.services.system_settings import SystemSettingsService


class PlaybackInfoService:
    def __init__(self, db, capability_resolver) -> None:
        self.db = db
        self.capability_resolver = capability_resolver

    async def get_playback_info(
        self,
        *,
        media_id: UUID,
        current_user,
        permissions,
        params,
    ) -> dict:
        media_item = await MediaService(self.db).get_by_id(media_id)
        if not media_item:
            raise HTTPException(status_code=404, detail="Media not found")
        require_media_play_access(current_user, permissions, media_item)

        capabilities, device, profile_id = await self.capability_resolver(
            self.db,
            current_user,
            params.profile_id,
            params.device_guid,
        )
        decision_service = PlaybackDecisionService()
        client_context = decision_service.client_context(
            capabilities=capabilities,
            supported_video_codecs=params.supported_video_codecs,
            supported_audio_codecs=params.supported_audio_codecs,
            supported_containers=params.supported_containers,
            client_max_resolution=params.client_max_resolution,
            client_max_bitrate=params.client_max_bitrate,
        )

        files = await self._media_files(media_id)
        if params.media_source_id and all(
            file.guid != params.media_source_id for file in files
        ):
            raise HTTPException(status_code=404, detail="Media source not found")
        if not files:
            return self._unavailable_payload(media_id, device)

        transcoding_settings = (
            await SystemSettingsService(self.db).get_transcoding_settings()
        )
        media_sources = self._media_source_payloads(
            media_item=media_item,
            media_id=media_id,
            files=files,
            permissions=permissions,
            params=params,
            decision_service=decision_service,
            client_context=client_context,
            transcoding_settings=transcoding_settings,
            profile_id=profile_id,
            device=device,
        )
        return self._ready_payload(
            media_id=media_id,
            device=device,
            profile_id=profile_id,
            client_context=client_context,
            media_sources=media_sources,
            media_source_id=params.media_source_id,
        )

    async def _media_files(self, media_id: UUID) -> list[MediaFile]:
        result = await self.db.execute(
            select(MediaFile).where(MediaFile.media_item_guid == media_id)
        )
        return list(result.scalars().all())

    @staticmethod
    def _unavailable_payload(media_id: UUID, device: Device | None) -> dict:
        return {
            "status": "unavailable",
            "media_id": str(media_id),
            "device_guid": str(device.guid) if device else None,
            "media_sources": [],
            "selected_media_source_id": None,
            "message": "No media files are available for playback.",
        }

    @staticmethod
    def _media_source_payloads(
        *,
        media_item,
        media_id: UUID,
        files: list[MediaFile],
        permissions,
        params,
        decision_service: PlaybackDecisionService,
        client_context,
        transcoding_settings: dict,
        profile_id: str | None,
        device: Device | None,
    ) -> list[dict]:
        effective_audio_bitrate = (
            transcoding_settings.get("default_audio_bitrate") or "128k"
        )
        media_sources = []
        for media_file in files:
            try:
                decision = decision_service.decide_source(
                    media_item=media_item,
                    media_file=media_file,
                    permissions=permissions,
                    context=client_context,
                    transcoding_settings=transcoding_settings,
                    requested_video_codec=params.video_codec,
                    requested_audio_codec=params.audio_codec,
                    requested_audio_bitrate=effective_audio_bitrate,
                    requested_resolution=params.resolution,
                )
            except PlaybackDecisionError as exc:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail=exc.detail,
                ) from exc

            media_sources.append(
                decision.media_source_payload(
                    media_id=media_id,
                    profile_id=profile_id,
                    device_guid=device.guid if device else None,
                    supported_containers=client_context.supported_containers,
                    max_bitrate=client_context.max_bitrate,
                )
            )
        return media_sources

    @staticmethod
    def _ready_payload(
        *,
        media_id: UUID,
        device: Device | None,
        profile_id: str | None,
        client_context,
        media_sources: list[dict],
        media_source_id: UUID | None,
    ) -> dict:
        selected = next(
            (
                source
                for source in media_sources
                if (
                    (media_source_id is None or source["id"] == str(media_source_id))
                    and source["playback_method"]
                    in {"direct_play", "direct_stream", "transcode"}
                )
            ),
            None,
        )
        return {
            "status": "ready" if selected else "unsupported",
            "media_id": str(media_id),
            "device_guid": str(device.guid) if device else None,
            "device_id": device.device_id if device else None,
            "profile_id": profile_id,
            "client_capabilities": client_context.response_payload(profile_id),
            "selected_media_source_id": selected["id"] if selected else None,
            "media_sources": media_sources,
        }
