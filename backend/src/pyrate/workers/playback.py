"""Playback worker domain helpers."""

from __future__ import annotations

import logging

from pyrate.database import sessionmanager
from pyrate.services.computing import ComputingService
from pyrate.services.play import start_transcode_container
from pyrate.services.redis_event import get_redis_event_service
from pyrate.services.transcoding_session import get_transcoding_session_service

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
        checked = restarted = failed = 0
        async with sessionmanager.session() as db:
            redis_service = get_redis_event_service()

            async def _publish(channel, event, data):
                await redis_service.publish(channel=channel, event=event, data=data)

            async with ComputingService(db) as computing_service:
                for session in sessions:
                    if session.status == "failed":
                        continue
                    checked += 1
                    if await self._is_task_running(computing_service, session):
                        continue

                    outcome = await session_service.recover_crashed_session(
                        session,
                        self.max_retries,
                        restart_fn=self._restart_fn(db),
                        publish_fn=_publish,
                    )
                    restarted += 1 if outcome == "restarted" else 0
                    failed += 1 if outcome == "failed" else 0
        return {"checked": checked, "restarted": restarted, "failed": failed}

    async def _is_task_running(self, computing_service, session) -> bool:
        try:
            tasks = await computing_service.get_tasks_by_label(
                "transcode.session_id",
                session.session_id,
            )
            if not tasks:
                return False
            return tasks[0].get("status") in ("running", "pending")
        except Exception as exc:
            logger.warning(
                "Failed to check container status for %s: %s",
                session.session_id,
                exc,
            )
            return True

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
