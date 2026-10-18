"""Playback worker domain helpers."""

from __future__ import annotations

import logging

from streamarr.database import sessionmanager
from streamarr.services.computing import ComputingService
from streamarr.services.play import start_transcode_container
from streamarr.services.redis_event import get_redis_event_service
from streamarr.services.transcoding_session import get_transcoding_session_service

logger = logging.getLogger(__name__)


class TranscodeMonitorWorker:
    def __init__(self, max_retries: int) -> None:
        self.max_retries = max_retries

    async def monitor_active_transcodes(self) -> dict:
        logger.debug("Checking active transcoding sessions")
        try:
            session_service = get_transcoding_session_service()
            sessions = await session_service.get_all_sessions(active_only=True)
            if not sessions:
                return {"checked": 0, "restarted": 0, "failed": 0}

            result = await self._monitor_sessions(session_service, sessions)
            if result["restarted"] or result["failed"]:
                logger.info("Transcode monitor: %s", result)
            return result
        except Exception as exc:
            logger.error("Transcode monitor failed: %s", exc, exc_info=True)
            raise

    async def _monitor_sessions(self, session_service, sessions) -> dict:
        checked = restarted = failed = completed = 0
        async with sessionmanager.session() as db:
            redis_service = get_redis_event_service()

            async def _publish(channel, event, data):
                await redis_service.publish(channel=channel, event=event, data=data)

            async with ComputingService(db) as computing_service:
                for session in sessions:
                    if session.status in ("failed", "completed"):
                        continue
                    checked += 1
                    task_status = await self._task_status(computing_service, session)
                    if task_status in ("running", "pending"):
                        continue
                    if task_status == "completed":
                        # ffmpeg reached the end of the media and exited cleanly,
                        # so every segment is on disk and the player may well
                        # still be working through them. Restarting here
                        # re-encodes from position 0 over the very files the
                        # client is downloading - which shows up as the stream
                        # stalling every few minutes, plus a wasted GPU pass per
                        # cycle, forever.
                        await session_service.mark_completed(session.session_id)
                        completed += 1
                        continue

                    outcome = await session_service.recover_crashed_session(
                        session,
                        self.max_retries,
                        restart_fn=self._restart_fn(db),
                        publish_fn=_publish,
                    )
                    restarted += 1 if outcome == "restarted" else 0
                    failed += 1 if outcome == "failed" else 0
        return {
            "checked": checked,
            "restarted": restarted,
            "failed": failed,
            "completed": completed,
        }

    async def _task_status(self, computing_service, session) -> str | None:
        """Status of the session's container, or None when it no longer exists.

        Returns the real status rather than a yes/no, because "no container"
        means different things: it crashed (restart), or it finished encoding
        the media (leave it alone).
        """
        try:
            tasks = await computing_service.get_tasks_by_label(
                "transcode.session_id",
                session.session_id,
            )
            if not tasks:
                return None
            statuses = [task.get("status") for task in tasks]
            for live in ("running", "pending"):
                if live in statuses:
                    return live
            return statuses[0]
        except Exception as exc:
            logger.warning(
                "Failed to check container status for %s: %s",
                session.session_id,
                exc,
            )
            return "running"

    @staticmethod
    def _restart_fn(db):
        async def _restart(session):
            await start_transcode_container(
                db=db,
                input_path=session.input_path,
                rel_output=f"/temp/{session.session_id}.m3u8",
                segment_pattern=f"/temp/{session.session_id}_%03d.ts",
                session_id=session.session_id,
                video_codec=session.video_codec,
                audio_codec=session.audio_codec,
                video_bitrate=session.video_bitrate,
                audio_bitrate=session.audio_bitrate,
                start_position=session.start_position or 0,
                resolution=session.resolution,
                user_guid=session.user_guid,
                user_name=session.user_name,
                content_type=session.content_type,
                content_id=session.content_id,
                content_title=session.content_title,
            )

        return _restart
