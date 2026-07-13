"""Transcoding session service for managing streaming sessions in Redis."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import redis.asyncio as redis
from aiodocker import Docker

from streamarr.config import settings
from streamarr.schemas.transcoding import (
    TranscodingSession,
    TranscodingSessionCreate,
    TranscodingSessionRead,
    TranscodingSessionsResponse,
)

logger = logging.getLogger(__name__)

# Redis key prefix for transcoding sessions
REDIS_KEY_PREFIX = "streamarr:transcoding:session:"
REDIS_SESSIONS_SET = "streamarr:transcoding:sessions"


class TranscodingSessionService:
    """Service for managing transcoding sessions in Redis."""

    def __init__(self):
        self._redis: redis.Redis | None = None
        self._redis_loop: asyncio.AbstractEventLoop | None = None

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        current_loop = asyncio.get_running_loop()
        if self._redis is not None and self._redis_loop is not current_loop:
            await self.close()
        if self._redis is None:
            self._redis = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            self._redis_loop = current_loop
        return self._redis

    async def close(self):
        """Close Redis connection."""
        redis_client = self._redis
        redis_loop = self._redis_loop
        self._redis = None
        self._redis_loop = None
        if redis_client and (redis_loop is None or not redis_loop.is_closed()):
            try:
                await redis_client.aclose()
            except RuntimeError as exc:
                logger.debug("Redis close skipped after loop shutdown: %s", exc)

    def _get_session_key(self, session_id: str) -> str:
        """Get Redis key for a session."""
        return f"{REDIS_KEY_PREFIX}{session_id}"

    def _get_session_lock_key(self, session_id: str) -> str:
        """Get Redis key for the per-session write mutex."""
        return f"{REDIS_KEY_PREFIX}lock:{session_id}"

    @asynccontextmanager
    async def _session_lock(self, session_id: str, ttl: int = 5):
        """Serialize read-modify-write updates to a single session's JSON blob."""
        r = await self._get_redis()
        lock_key = self._get_session_lock_key(session_id)
        acquired = False
        for _ in range(100):
            if await r.set(lock_key, "1", nx=True, ex=ttl):
                acquired = True
                break
            await asyncio.sleep(0.02)
        try:
            yield
        finally:
            if acquired:
                try:
                    await r.delete(lock_key)
                except Exception as exc:
                    logger.debug("Session lock release failed for %s: %s", session_id, exc)

    def _get_quarantine_key(self, content_id: str) -> str:
        """Get Redis key for a quarantined content id."""
        return f"streamarr:transcoding:quarantine:{content_id}"

    async def quarantine_content(
        self, content_id: str, ttl_seconds: int = 600, reason: str = "repeated_failure"
    ) -> None:
        """Mark a ``content_id`` as un-transcodable for ``ttl_seconds``.

        Subsequent ``play_media``/``seek_media`` calls should reject quickly
        instead of repeatedly spinning up doomed ffmpeg containers.
        """
        try:
            r = await self._get_redis()
            await r.set(self._get_quarantine_key(content_id), reason, ex=ttl_seconds)
            logger.warning(
                "Quarantined content %s for %ss (reason: %s)",
                content_id, ttl_seconds, reason,
            )
        except Exception as e:
            logger.warning("Failed to quarantine content %s: %s", content_id, e)

    async def is_quarantined(self, content_id: str) -> str | None:
        """Return the quarantine reason if ``content_id`` is currently blocked."""
        try:
            r = await self._get_redis()
            value = await r.get(self._get_quarantine_key(content_id))
            if value is None:
                return None
            return value.decode() if isinstance(value, bytes) else str(value)
        except Exception as e:
            logger.warning("Failed to check quarantine for %s: %s", content_id, e)
            return None

    async def create_session(
        self, session_data: TranscodingSessionCreate
    ) -> TranscodingSession:
        """Create a new transcoding session in Redis."""
        r = await self._get_redis()

        session = TranscodingSession(
            session_id=session_data.session_id,
            user_guid=str(session_data.user_guid) if session_data.user_guid else None,
            user_name=session_data.user_name,
            content_type=session_data.content_type,
            content_id=str(session_data.content_id),
            content_title=session_data.content_title,
            container_id=session_data.container_id,
            job_name=session_data.job_name,
            job_namespace=session_data.job_namespace,
            runtime_type=session_data.runtime_type,
            video_codec=session_data.video_codec,
            audio_codec=session_data.audio_codec,
            video_bitrate=session_data.video_bitrate,
            audio_bitrate=session_data.audio_bitrate,
            resolution=session_data.resolution,
            start_position=session_data.start_position,
            input_path=session_data.input_path,
            started_at=datetime.now(UTC),
            last_accessed_at=datetime.now(UTC),
            is_active=True,
        )

        session_key = self._get_session_key(session.session_id)
        session_data_json = json.dumps(session.to_redis_dict())

        # Store session with 2h expiry (sessions should be cleaned up much sooner)
        await r.set(session_key, session_data_json, ex=7200)

        # Add to sessions set
        await r.sadd(REDIS_SESSIONS_SET, session.session_id)

        logger.info(
            "Created transcoding session: %s for %s %s",
            session.session_id, session.content_type, session.content_id,
        )

        return session

    async def get_session(self, session_id: str) -> TranscodingSession | None:
        """Get a transcoding session by ID."""
        r = await self._get_redis()

        session_key = self._get_session_key(session_id)
        session_data = await r.get(session_key)

        if not session_data:
            return None

        try:
            data = json.loads(session_data)
            return TranscodingSession.from_redis_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Error parsing session data for %s: %s", session_id, e)
            return None

    async def get_session_logs(
        self,
        session: TranscodingSession,
        tail_lines: int = 100,
    ) -> str:
        """Return runtime logs for a transcoding session."""
        if session.runtime_type == "kubernetes" and session.job_name:
            try:
                from streamarr.services.kubernetes import get_kubernetes_transcoding_service

                k8s_service = get_kubernetes_transcoding_service()
                return await k8s_service.get_job_logs(
                    session.job_name,
                    tail_lines=tail_lines,
                )
            except Exception as e:
                return f"Error retrieving Kubernetes logs: {e}"

        try:
            async with Docker() as docker:
                containers = await docker.containers.list(
                    all=True,
                    filters={"label": [f"transcode.session_id={session.session_id}"]},
                )
                if containers:
                    log_lines = await containers[0].log(
                        stdout=True,
                        stderr=True,
                        tail=str(tail_lines),
                    )
                    return "".join(log_lines)

                if session.container_id:
                    try:
                        container = await docker.containers.get(session.container_id)
                        log_lines = await container.log(
                            stdout=True,
                            stderr=True,
                            tail=str(tail_lines),
                        )
                        return "".join(log_lines)
                    except Exception:
                        return "Container not found. It may have been removed."

                return "No container found for this session"
        except Exception as e:
            return f"Error retrieving Docker logs: {e}"

    async def get_session_runtime_status(
        self,
        session: TranscodingSession,
    ) -> dict:
        """Return provider-specific live runtime status for a session."""
        if session.runtime_type == "kubernetes" and session.job_name:
            try:
                from streamarr.services.kubernetes import get_kubernetes_transcoding_service

                k8s_service = get_kubernetes_transcoding_service()
                return {"kubernetes": await k8s_service.get_job_status(session.job_name)}
            except Exception as e:
                return {"kubernetes_error": str(e)}

        if session.container_id:
            try:
                async with Docker() as docker:
                    container = await docker.containers.get(session.container_id)
                    info = await container.show()
                    state = info.get("State", {})
                    return {
                        "docker": {
                            "container_id": session.container_id,
                            "state": state.get("Status"),
                            "running": state.get("Running"),
                            "started_at": state.get("StartedAt"),
                            "finished_at": state.get("FinishedAt"),
                            "exit_code": state.get("ExitCode"),
                        }
                    }
            except Exception as e:
                return {"docker_error": str(e)}

        return {}

    async def update_session_access(
        self, session_id: str, throttle_seconds: int = 60
    ) -> bool:
        """Update the last accessed time for a session.

        To avoid excessive Redis writes on every segment request, the update is
        throttled: if ``last_accessed_at`` was updated less than
        ``throttle_seconds`` ago the write is skipped.
        """
        session = await self.get_session(session_id)
        if not session:
            return False

        now = datetime.now(UTC)
        if throttle_seconds and session.last_accessed_at:
            elapsed = (now - session.last_accessed_at).total_seconds()
            if elapsed < throttle_seconds:
                return True  # Skip write, still considered successful

        async with self._session_lock(session_id):
            r = await self._get_redis()
            session = await self.get_session(session_id)
            if not session:
                return False

            session.last_accessed_at = datetime.now(UTC)

            session_key = self._get_session_key(session_id)
            session_data_json = json.dumps(session.to_redis_dict())

            # Refresh expiry (2h)
            await r.set(session_key, session_data_json, ex=7200)

        return True

    async def update_session_container(
        self, session_id: str, container_id: str
    ) -> bool:
        """Update the container ID for a session."""
        r = await self._get_redis()

        session = await self.get_session(session_id)
        if not session:
            return False

        session.container_id = container_id
        session.last_accessed_at = datetime.now(UTC)

        session_key = self._get_session_key(session_id)
        session_data_json = json.dumps(session.to_redis_dict())

        await r.set(session_key, session_data_json, ex=7200)

        return True

    async def get_all_sessions(
        self, active_only: bool = False
    ) -> list[TranscodingSession]:
        """Get all transcoding sessions."""
        r = await self._get_redis()

        session_ids = await r.smembers(REDIS_SESSIONS_SET)
        sessions = []

        for session_id in session_ids:
            session = await self.get_session(session_id)
            if session:
                if active_only and not session.is_active:
                    continue
                sessions.append(session)
            else:
                # Clean up stale session ID from set
                await r.srem(REDIS_SESSIONS_SET, session_id)

        # Sort by started_at descending
        sessions.sort(key=lambda s: s.started_at, reverse=True)

        return sessions

    async def get_sessions_with_status(
        self, active_only: bool = False
    ) -> TranscodingSessionsResponse:
        """Get sessions formatted as API response, enriched with live container status and transcode progress.

        This method:
        1. Fetches all sessions (with auto-cleanup of stale ones)
        2. Queries Docker for live container statuses
        3. Counts generated segments for transcode progress

        Args:
            active_only: Only return active sessions

        Returns:
            TranscodingSessionsResponse with enriched session data
        """
        response = await self.get_sessions_response(active_only=active_only)

        # Enrich with live container status
        try:
            async with Docker() as docker:
                running_containers = await docker.containers.list(all=True)
                container_statuses = {}
                for container in running_containers:
                    info = await container.show()
                    container_id = info["Id"]
                    labels = info.get("Config", {}).get("Labels", {})
                    session_id_label = labels.get("transcode.session_id")
                    state = info.get("State", {})
                    status = (
                        "running"
                        if state.get("Running")
                        else state.get("Status", "exited")
                    )
                    if session_id_label:
                        container_statuses[session_id_label] = status
                    if container_id:
                        container_statuses[container_id] = status

                for session in response.sessions:
                    session.container_status = (
                        container_statuses.get(session.session_id)
                        or container_statuses.get(session.container_id)
                        or "not_found"
                    )
        except Exception as e:
            logger.warning("Failed to query Docker for container statuses: %s", e)
            for session in response.sessions:
                session.container_status = "unknown"

        # Enrich with transcode progress (count generated segments)
        import glob
        from pathlib import Path

        for session in response.sessions:
            try:
                segment_pattern = f"/temp/{session.session_id}_*.ts"
                segments = glob.glob(segment_pattern)
                session.transcoded_segments = len(segments)

                # Read m3u8 to get expected segment count
                m3u8_path = Path(f"/temp/{session.session_id}.m3u8")
                if m3u8_path.exists():
                    content = m3u8_path.read_text()
                    extinf_count = content.count("#EXTINF:")
                    if extinf_count > 0:
                        session.total_segments = extinf_count
                        session.transcode_progress = min(
                            len(segments) / extinf_count, 1.0
                        )
            except Exception as e:
                logger.debug("Failed to compute transcode progress for session %s: %s", session.session_id, e)

        return response

    async def get_sessions_response(
        self, active_only: bool = False, auto_cleanup: bool = True
    ) -> TranscodingSessionsResponse:
        """Get sessions formatted as API response.

        Args:
            active_only: Only return active sessions
            auto_cleanup: Automatically clean up stale sessions before returning
        """
        # Auto-cleanup stale sessions (containers that are no longer running)
        if auto_cleanup:
            try:
                cleaned = await self.cleanup_stale_sessions()
                if cleaned > 0:
                    logger.info("Auto-cleaned %s stale sessions", cleaned)
            except Exception as e:
                logger.warning("Auto-cleanup failed: %s", e)

        sessions = await self.get_all_sessions(active_only=active_only)

        session_reads = [TranscodingSessionRead.from_session(s) for s in sessions]
        active_count = sum(1 for s in sessions if s.is_active)

        return TranscodingSessionsResponse(
            sessions=session_reads,
            total=len(sessions),
            active_count=active_count,
        )

    async def get_user_sessions(self, user_guid: str) -> list[TranscodingSession]:
        """Get all sessions for a specific user."""
        all_sessions = await self.get_all_sessions()
        return [s for s in all_sessions if s.user_guid == user_guid]

    async def terminate_active_content_sessions(
        self,
        content_id: str,
        *,
        user_guid: str | None = None,
        exclude_session_id: str | None = None,
    ) -> list[dict]:
        """Terminate active sessions for a media item.

        This keeps API routers from reaching into Docker/Kubernetes directly
        and lets session cleanup follow the same provider-aware path as
        explicit session termination.
        """
        sessions = await self.get_all_sessions(active_only=True)
        results = []
        for session in sessions:
            if session.content_id != content_id:
                continue
            if user_guid is not None and session.user_guid != user_guid:
                continue
            if exclude_session_id and session.session_id == exclude_session_id:
                continue
            results.append(await self.terminate_session(session.session_id))
        return results

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session from Redis (does not stop container)."""
        r = await self._get_redis()

        session_key = self._get_session_key(session_id)

        # Remove from both key and set
        await r.delete(session_key)
        await r.srem(REDIS_SESSIONS_SET, session_id)

        logger.info("Deleted transcoding session: %s", session_id)

        return True

    async def increment_retry(self, session_id: str) -> int:
        """Increment retry count and set status to 'restarting'. Returns new count."""
        async with self._session_lock(session_id):
            r = await self._get_redis()
            session = await self.get_session(session_id)
            if not session:
                return -1

            session.retry_count += 1
            session.status = "restarting"
            session.last_accessed_at = datetime.now(UTC)
            session.last_retry_at = datetime.now(UTC)

            session_key = self._get_session_key(session_id)
            await r.set(session_key, json.dumps(session.to_redis_dict()), ex=7200)
            return session.retry_count

    async def mark_failed(self, session_id: str) -> bool:
        """Mark a session as failed."""
        r = await self._get_redis()
        session = await self.get_session(session_id)
        if not session:
            return False

        session.status = "failed"
        session.is_active = False
        session.last_accessed_at = datetime.now(UTC)

        session_key = self._get_session_key(session_id)
        await r.set(session_key, json.dumps(session.to_redis_dict()), ex=7200)

        logger.info("Marked session %s as failed", session_id)
        return True

    async def mark_active(self, session_id: str, container_id: str | None = None) -> bool:
        """Mark a session as active again (after successful restart)."""
        r = await self._get_redis()
        session = await self.get_session(session_id)
        if not session:
            return False

        session.status = "active"
        session.is_active = True
        session.last_accessed_at = datetime.now(UTC)
        if container_id:
            session.container_id = container_id

        session_key = self._get_session_key(session_id)
        await r.set(session_key, json.dumps(session.to_redis_dict()), ex=7200)
        return True

    async def terminate_session(self, session_id: str) -> dict:
        """Terminate a transcoding session by stopping its container/job and removing from Redis."""
        session = await self.get_session(session_id)

        if not session:
            return {"success": False, "message": "Session not found"}

        result = {
            "success": True,
            "session_id": session_id,
            "container_stopped": False,
            "job_deleted": False,
        }

        # Handle Docker containers
        if session.container_id:
            try:
                async with Docker() as docker:
                    container = await docker.containers.get(session.container_id)
                    await container.stop()
                    await container.delete()
                    result["container_stopped"] = True
                    logger.info(
                        "Stopped container %s for session %s",
                        session.container_id, session_id,
                    )
            except Exception as e:
                logger.warning("Could not stop container %s: %s", session.container_id, e)
                result["container_error"] = str(e)

            # Also try to find and stop container by session ID label
            try:
                async with Docker() as docker:
                    containers = await docker.containers.list()
                    for container in containers:
                        info = await container.show()
                        labels = info.get("Config", {}).get("Labels", {})
                        if labels.get("transcode.session_id") == session_id:
                            await container.stop()
                            await container.delete()
                            result["container_stopped"] = True
                            logger.info("Stopped container by label for session %s", session_id)
                            break
            except Exception as e:
                logger.warning("Error searching for container by label: %s", e)

        # Mark session as inactive and delete
        session.is_active = False
        await self.delete_session(session_id)

        return result

    async def recover_crashed_session(
        self,
        session: "TranscodingSession",
        max_retries: int,
        *,
        restart_fn=None,
        publish_fn=None,
    ) -> str:
        """Attempt to recover a crashed transcoding session.

        Handles the full recovery flow:
        - If retries are exhausted, marks as failed and publishes a
          ``transcode_failed`` event.
        - Otherwise, calls ``restart_fn`` to re-create the container and
          publishes a ``transcode_restarting`` event.

        Args:
            session: The transcoding session to recover.
            max_retries: Maximum number of restart attempts.
            restart_fn: Async callable that restarts the transcode
                container.  Signature::

                    async def restart_fn(session) -> None

            publish_fn: Optional async callable to publish WebSocket events.
                Signature::

                    async def publish_fn(channel, event, data) -> None

        Returns:
            ``"failed"`` if retries are exhausted or the restart itself
            raised, ``"restarted"`` on success, or ``"skipped"`` when no
            action was needed.
        """
        logger.warning(
            "Transcode container stopped for session %s (retry %s/%s)",
            session.session_id, session.retry_count, max_retries,
        )

        # Exponential backoff between restart attempts: never restart faster
        # than the schedule below, regardless of how often the monitor runs.
        # This prevents busy-loop restarts when ffmpeg fails immediately.
        if session.last_retry_at is not None:
            # 30s after first retry, 2min after second, 8min after third, ...
            min_wait = 30 * (4 ** max(session.retry_count - 1, 0))
            elapsed = (
                datetime.now(UTC) - session.last_retry_at
            ).total_seconds()
            if elapsed < min_wait:
                logger.info(
                    "Backoff active for session %s: waited %.0fs of %ss",
                    session.session_id, elapsed, min_wait,
                )
                return "skipped"

        if session.retry_count >= max_retries:
            await self.mark_failed(session.session_id)
            await self.quarantine_content(
                session.content_id, ttl_seconds=600, reason="container_crashed"
            )

            if session.user_guid and publish_fn:
                try:
                    await publish_fn(
                        channel=f"user:{session.user_guid}",
                        event="transcode_failed",
                        data={
                            "session_id": session.session_id,
                            "content_id": session.content_id,
                            "content_title": session.content_title,
                            "error": "container_crashed",
                            "retries_exhausted": True,
                        },
                    )
                except Exception as e:
                    logger.warning("Failed to publish transcode_failed event: %s", e)

            return "failed"

        retry_count = await self.increment_retry(session.session_id)
        if retry_count < 0:
            return "failed"
        logger.info(
            "Restarting transcode for session %s (attempt %s/%s)",
            session.session_id, retry_count, max_retries,
        )

        try:
            if restart_fn:
                await restart_fn(session)

                # start_transcode_container overwrites the Redis session with
                # retry_count=0.  Re-apply the correct count.
                for _ in range(retry_count):
                    await self.increment_retry(session.session_id)
            await self.mark_active(session.session_id)

            if session.user_guid and publish_fn:
                try:
                    await publish_fn(
                        channel=f"user:{session.user_guid}",
                        event="transcode_restarting",
                        data={
                            "session_id": session.session_id,
                            "content_id": session.content_id,
                            "content_title": session.content_title,
                            "retry_count": retry_count,
                            "max_retries": max_retries,
                        },
                    )
                except Exception as e:
                    logger.warning("Failed to publish transcode_restarting event: %s", e)

            logger.info("Successfully restarted transcode for %s", session.session_id)
            return "restarted"

        except Exception as e:
            logger.error(
                "Failed to restart transcode for %s: %s",
                session.session_id, e, exc_info=True,
            )
            if retry_count >= max_retries:
                await self.mark_failed(session.session_id)
                await self.quarantine_content(
                    session.content_id,
                    ttl_seconds=600,
                    reason="restart_failed",
                )
            return "failed"

    async def cleanup_stale_sessions(self) -> int:
        """Clean up sessions whose containers/jobs are no longer running AND haven't been accessed recently.

        Sessions are kept if:
        - The container/job is still running, OR
        - The session was accessed within the last 30 minutes (transcoding may be complete but user is still watching)
        """
        import time

        sessions = await self.get_all_sessions()
        cleaned_count = 0

        # Grace period: keep session for 5 minutes after last access even if container stopped.
        # With last_accessed_at now updated on every segment/playlist request (throttled),
        # a 5-minute gap reliably indicates the user has stopped watching.
        GRACE_PERIOD_SECONDS = 5 * 60  # 5 minutes
        current_time = time.time()

        try:
            # Get running Docker containers
            running_docker_ids = set()
            running_docker_session_ids = set()
            try:
                async with Docker() as docker:
                    running_containers = await docker.containers.list()
                    for container in running_containers:
                        info = await container.show()
                        running_docker_ids.add(info["Id"])
                        labels = info.get("Config", {}).get("Labels", {})
                        if "transcode.session_id" in labels:
                            running_docker_session_ids.add(
                                labels["transcode.session_id"]
                            )
            except Exception as e:
                logger.warning("Could not list Docker containers: %s", e)

            for session in sessions:
                if not session.is_active:
                    continue

                is_running = False

                # Check if Docker container is still running
                is_running = (
                    session.container_id in running_docker_ids
                    or session.session_id in running_docker_session_ids
                )

                if not is_running:
                    # Container stopped - check if session was recently accessed
                    last_accessed = session.last_accessed_at
                    # last_accessed_at is a naive UTC datetime; compute delta without timestamps
                    if isinstance(last_accessed, datetime):
                        time_since_access = (datetime.now(UTC) - last_accessed).total_seconds()
                    else:
                        # Fallback: treat as float Unix timestamp
                        time_since_access = current_time - float(last_accessed)

                    if time_since_access < GRACE_PERIOD_SECONDS:
                        # Session still in use, don't delete yet
                        logger.debug(
                            "Session %s container stopped but accessed %ss ago, keeping for now",
                            session.session_id, int(time_since_access),
                        )
                        continue

                    logger.info(
                        "Cleaning up stale session: %s (last accessed %ss ago)",
                        session.session_id, int(time_since_access),
                    )
                    session.is_active = False
                    await self.delete_session(session.session_id)
                    from streamarr.services.storage_cleanup import cleanup_session_temp_files
                    temp_result = cleanup_session_temp_files(session.session_id)
                    if temp_result["deleted"]:
                        logger.info(
                            "Cleaned up %d temp files for stale session %s",
                            temp_result["deleted"], session.session_id,
                        )
                    cleaned_count += 1

        except Exception as e:
            logger.error("Error during session cleanup: %s", e)

        return cleaned_count


# Global service instance
_session_service: TranscodingSessionService | None = None


def get_transcoding_session_service() -> TranscodingSessionService:
    """Get the global transcoding session service instance."""
    global _session_service
    if _session_service is None:
        _session_service = TranscodingSessionService()
    return _session_service
