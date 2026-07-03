"""Song identification orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid as uuid_module
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from pyrate.models.media import MediaFile
from pyrate.services.computing import (
    ComputingService,
    _ffmpeg_runtime_user,
    build_media_volumes,
)
from pyrate.services.system_settings import SystemSettingsService

logger = logging.getLogger(__name__)

DEFAULT_FFMPEG_IMAGE = "lscr.io/linuxserver/ffmpeg:latest"
FFMPEG_TASK_TIMEOUT_SECONDS = 60
FFMPEG_TASK_POLL_SECONDS = 2


class SongIdentificationService:
    def __init__(self, db) -> None:
        self.db = db

    async def identify_song(self, media_id: UUID, position: float) -> dict:
        file = await self._media_file(media_id)
        start, duration = self._segment(file.duration, position)
        tmp_path = f"/temp/shazam_{uuid_module.uuid4().hex}.wav"

        task_status, output = await self._extract_audio(file.file_path, start, duration, tmp_path)
        if task_status != "completed" or not os.path.exists(tmp_path):
            self._remove_tmp(tmp_path)
            logger.warning(
                "Audio extraction failed: status=%s output=%s",
                task_status,
                (output or "")[:500],
            )
            raise HTTPException(status_code=500, detail="Audio extraction failed")

        song = await self._identify_tmp(tmp_path)
        return {"status": "identified", "song": song} if song else {
            "status": "no_match",
            "song": None,
        }

    async def _media_file(self, media_id: UUID) -> MediaFile:
        result = await self.db.execute(
            select(MediaFile).where(MediaFile.media_item_guid == media_id)
        )
        file = result.scalars().first()
        if not file:
            raise HTTPException(
                status_code=404,
                detail="No file found for this media item",
            )
        return file

    @staticmethod
    def _segment(file_duration: float | None, position: float) -> tuple[float, float]:
        start = max(0, position - 7.5)
        duration = 15
        if file_duration and start + duration > file_duration:
            duration = max(5, file_duration - start)
        return start, duration

    async def _extract_audio(
        self,
        file_path: str,
        start: float,
        duration: float,
        tmp_path: str,
    ) -> tuple[str | None, str | None]:
        volumes = build_media_volumes(
            include_writable_temp=True,
            include_cache=False,
            include_downloads=True,
            read_only=True,
        )
        transcoding_settings = await SystemSettingsService(
            self.db
        ).get_transcoding_settings()
        ffmpeg_image = transcoding_settings.get("ffmpeg_image", DEFAULT_FFMPEG_IMAGE)
        env = _ffmpeg_runtime_user()
        cmd = [
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(max(0, int(start))),
            "-t",
            str(max(1, int(duration))),
            "-i",
            file_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            "-y",
            tmp_path,
        ]

        async with ComputingService(self.db) as computing:
            task_id = await computing.start_task(
                image=ffmpeg_image,
                command=cmd,
                env=env,
                volumes=volumes,
                timeout_seconds=FFMPEG_TASK_TIMEOUT_SECONDS,
                labels={
                    "task": "identify_song",
                    "pyrate.task_type": "song_identification",
                    "pyrate.tool": "ffmpeg",
                },
                entrypoint=["ffmpeg"],
            )
            task_status = None
            attempts = FFMPEG_TASK_TIMEOUT_SECONDS // FFMPEG_TASK_POLL_SECONDS
            for _ in range(attempts):
                task_status = await computing.get_task_status(task_id)
                if task_status in ("completed", "failed"):
                    break
                await asyncio.sleep(FFMPEG_TASK_POLL_SECONDS)

            output = await computing.get_task_logs(task_id)
            await computing.delete_task(task_id)
            return task_status, output

    async def _identify_tmp(self, tmp_path: str):
        try:
            from pyrate.metadata.shazam import ShazamProvider

            return await ShazamProvider().identify(tmp_path)
        finally:
            self._remove_tmp(tmp_path)

    @staticmethod
    def _remove_tmp(tmp_path: str) -> None:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
