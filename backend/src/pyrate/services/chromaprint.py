"""Chromaprint-based audio fingerprinting for intro/outro detection."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.media import MediaFile, MediaItem, MediaType
from pyrate.models.media_marker import MarkerSource, MarkerType
from pyrate.schemas.media_marker import MediaMarkerCreate
from pyrate.services.computing import ComputingService
from pyrate.services.media_marker import MediaMarkerService

logger = logging.getLogger(__name__)

INTRO_ANALYSIS_DURATION = 600  # First 10 minutes
OUTRO_ANALYSIS_DURATION = 300  # Last 5 minutes
CREDITS_ANALYSIS_DURATION = 900  # Last 15 minutes
MIN_CONFIDENCE = 0.7
CHROMAPRINT_IMAGE = "registry.gitlab.com/pyrate.media/ffmpeg:latest"


class ChromaprintService:
    """Audio fingerprint extraction and comparison for intro/outro detection."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def extract_and_store_fingerprint(self, media_file_guid: uuid.UUID) -> str | None:
        """
        Extract chromaprint fingerprint for a media file and store it in the DB.

        Returns the raw fingerprint string, or None on failure.
        """
        file = await self.db.get(MediaFile, media_file_guid)
        if not file:
            return None

        async with ComputingService(self.db) as computing:
            fp = await self._extract_fingerprint(
                computing, file.file_path, 0, INTRO_ANALYSIS_DURATION
            )

        if fp:
            file.chromaprint_raw = fp
            await self.db.commit()
            logger.info("Stored chromaprint for file %s", media_file_guid)

        return fp

    async def detect_intros_for_season(self, season_guid: uuid.UUID) -> dict:
        """
        Detect intros (chromaprint) and outros (black frame + silence) for all
        episodes in a season.
        """
        # Get all episodes for this season with their files
        episodes_result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.parent_guid == season_guid)
            .options(selectinload(MediaItem.files))
            .order_by(MediaItem.sequence_number)
        )
        episodes = episodes_result.scalars().all()

        if len(episodes) < 2:
            logger.info("Season %s has fewer than 2 episodes, skipping detection", season_guid)
            return {"detected": 0, "skipped": "too_few_episodes"}

        # Load cached fingerprints and extract missing ones
        fingerprints = {}
        need_extraction = []

        for ep in episodes:
            if not ep.files:
                continue
            file = ep.files[0]
            if file.chromaprint_raw:
                fingerprints[str(ep.guid)] = file.chromaprint_raw
            else:
                need_extraction.append((ep, file))

        # Extract missing fingerprints
        if need_extraction:
            async with ComputingService(self.db) as computing:
                for ep, file in need_extraction:
                    try:
                        fp = await self._extract_fingerprint(
                            computing, file.file_path, 0, INTRO_ANALYSIS_DURATION
                        )
                        if fp:
                            fingerprints[str(ep.guid)] = fp
                            file.chromaprint_raw = fp
                    except Exception as e:
                        logger.warning("Failed to extract fingerprint for %s: %s", ep.guid, e)

            if need_extraction:
                await self.db.commit()

        result = {}
        marker_service = MediaMarkerService(self.db)

        # --- Intro detection via chromaprint ---
        if len(fingerprints) >= 2:
            intro_segments = self._find_common_segments(fingerprints)
            valid_intros = [
                (s, e, c) for s, e, c in intro_segments if c >= MIN_CONFIDENCE
            ]
            if valid_intros:
                for idx, (seg_start, seg_end, confidence) in enumerate(valid_intros):
                    logger.info(
                        "Detected intro #%d for season %s: %.1f-%.1f (confidence: %.2f)",
                        idx + 1, season_guid, seg_start, seg_end, confidence,
                    )
                intro_markers = [
                    MediaMarkerCreate(
                        marker_type=MarkerType.INTRO,
                        start_seconds=s,
                        end_seconds=e,
                        source=MarkerSource.CHROMAPRINT,
                        confidence=c,
                        label=f"Intro {i + 1}" if len(valid_intros) > 1 else None,
                    )
                    for i, (s, e, c) in enumerate(valid_intros)
                ]
                stored = 0
                for ep in episodes:
                    if str(ep.guid) in fingerprints:
                        await marker_service.replace_markers(
                            ep.guid, MarkerType.INTRO, MarkerSource.CHROMAPRINT, intro_markers,
                        )
                        stored += 1
                result["intro"] = {
                    "detected": stored,
                    "segments": len(valid_intros),
                }

        # --- Outro detection via black frames + silence ---
        outro_stored = 0
        async with ComputingService(self.db) as computing:
            for ep in episodes:
                if not ep.files:
                    continue
                file = ep.files[0]
                if not file.duration or file.duration < OUTRO_ANALYSIS_DURATION:
                    continue
                try:
                    outro_start = await self._detect_outro(
                        computing, file.file_path, file.duration
                    )
                    if outro_start is not None:
                        await marker_service.create_marker(
                            ep.guid,
                            MediaMarkerCreate(
                                marker_type=MarkerType.OUTRO,
                                start_seconds=round(outro_start, 1),
                                end_seconds=round(file.duration, 1),
                                source=MarkerSource.SILENCE,
                                confidence=0.8,
                            ),
                        )
                        outro_stored += 1
                        logger.info(
                            "Detected outro for %s at %.1fs",
                            ep.title, outro_start,
                        )
                except Exception as e:
                    logger.warning("Outro detection failed for %s: %s", ep.guid, e)

        if outro_stored:
            result["outro"] = {"detected": outro_stored}

        if not result:
            logger.info("No intro or outro found for season %s", season_guid)
            return {"detected": 0, "skipped": "no_common_segment"}

        total = sum(r.get("detected", 0) for r in result.values())
        result["detected"] = total
        return result

    async def detect_credits_for_movie(self, media_item_guid: uuid.UUID) -> dict | None:
        """
        Detect credits in a movie using black frame detection.

        Analyzes the last 15 minutes of the movie for black frame transitions
        that typically indicate the start of credits.
        """
        result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.guid == media_item_guid)
            .options(selectinload(MediaItem.files))
        )
        media_item = result.scalar_one_or_none()
        if not media_item or not media_item.files:
            return None

        file = media_item.files[0]
        if not file.duration:
            return None

        async with ComputingService(self.db) as computing:
            credits_start = await self._detect_outro(
                computing, file.file_path, file.duration
            )

        if credits_start is None:
            return {"detected": False}

        marker_service = MediaMarkerService(self.db)
        await marker_service.create_marker(
            media_item_guid,
            MediaMarkerCreate(
                marker_type=MarkerType.CREDITS,
                start_seconds=credits_start,
                end_seconds=file.duration,
                source=MarkerSource.SILENCE,
                confidence=0.8,
            ),
        )

        return {"detected": True, "credits_start": credits_start}

    async def _extract_fingerprint(
        self, computing: ComputingService, file_path: str, start: float, duration: float
    ) -> str | None:
        """Extract audio fingerprint using fpcalc in a Docker container."""
        import shlex

        from pyrate.services.computing import build_media_volumes

        volumes = build_media_volumes(
            include_writable_temp=False,
            include_cache=False,
            include_downloads=False,
            read_only=True,
        )

        # fpcalc has no -offset option, so we still need a shell pipeline:
        # ffmpeg writes raw WAV to stdout and fpcalc consumes it. ``shlex.quote``
        # neutralises any shell metacharacters in ``file_path`` (this used to
        # be an f-string-into-sh injection vector).
        cmd = [
            "sh", "-c",
            (
                f"ffmpeg -ss {int(start)} -t {int(duration)} -i {shlex.quote(file_path)} "
                f"-ac 1 -ar 22050 -f wav pipe:1 2>/dev/null | fpcalc -raw -"
            ),
        ]

        try:
            task_id = await computing.start_task(
                image=CHROMAPRINT_IMAGE,
                command=cmd,
                volumes=volumes,
                labels={"task": "chromaprint"},
            )

            import asyncio
            for _ in range(60):  # Max 5 minutes
                status = await computing.get_task_status(task_id)
                if status in ("completed", "failed"):
                    break
                await asyncio.sleep(5)

            output = await computing.get_task_logs(task_id)
            await computing.delete_task(task_id)

            if status == "completed" and output:
                return output.strip()
            else:
                logger.warning("Fingerprint extraction failed: %s", output[:500] if output else "no output")
                return None

        except Exception as e:
            logger.error("Fingerprint extraction error: %s", e)
            return None

    def _find_common_segments(self, fingerprints: dict[str, str]) -> list[tuple[float, float, float]]:
        """
        Compare chromaprint fingerprints to find a common audio segment.

        Uses a sliding-window bit-correlation approach inspired by common media-server
        IntroSkipper plugin. Each chromaprint is a sequence of 32-bit integers
        where similar audio produces similar bit patterns.

        Returns (start_seconds, end_seconds, confidence) or None.
        """
        # Parse fpcalc -raw output into integer arrays
        # Format: DURATION=123\nFINGERPRINT=123,456,789,...
        parsed: dict[str, list[int]] = {}
        for ep_guid, raw in fingerprints.items():
            try:
                fp_line = ""
                for line in raw.split("\n"):
                    if line.startswith("FINGERPRINT="):
                        fp_line = line.split("=", 1)[1]
                        break
                if not fp_line:
                    continue
                ints = [int(x) & 0xFFFFFFFF for x in fp_line.split(",") if x.strip()]
                if len(ints) < 10:
                    continue
                parsed[ep_guid] = ints
            except Exception as e:
                logger.warning("Failed to parse fingerprint for %s: %s", ep_guid, e)

        if len(parsed) < 2:
            return None

        # Each integer covers ~0.1238 seconds of audio (8192 samples at 22050 Hz ÷ 2 overlap)
        SAMPLES_PER_ITEM = 0.1238

        # Compare all pairs and collect matching segments
        all_matches: list[tuple[float, float]] = []
        guids = list(parsed.keys())

        for i in range(len(guids)):
            for j in range(i + 1, len(guids)):
                fp_a = parsed[guids[i]]
                fp_b = parsed[guids[j]]
                match = self._correlate_fingerprints(fp_a, fp_b, SAMPLES_PER_ITEM)
                if match:
                    all_matches.append(match)

        if not all_matches:
            logger.info("No matching segments found across %d episodes", len(parsed))
            return []

        # Find consensus: group matches by proximity (within 5 seconds)
        clusters: list[list[tuple[float, float]]] = []
        for match in sorted(all_matches):
            placed = False
            for cluster in clusters:
                ref_start = cluster[0][0]
                if abs(match[0] - ref_start) < 5.0:
                    cluster.append(match)
                    placed = True
                    break
            if not placed:
                clusters.append([match])

        # Return ALL clusters that have enough matches (not just the best)
        min_cluster_size = max(1, len(parsed) // 3)
        total_pairs = len(parsed) * (len(parsed) - 1) / 2
        segments = []

        for cluster in sorted(clusters, key=lambda c: c[0][0]):
            if len(cluster) < min_cluster_size:
                continue
            avg_start = sum(m[0] for m in cluster) / len(cluster)
            avg_end = sum(m[1] for m in cluster) / len(cluster)
            confidence = len(cluster) / total_pairs

            logger.info(
                "Found common segment: %.1f-%.1f (confidence: %.2f, %d pairs matched)",
                avg_start, avg_end, confidence, len(cluster),
            )
            segments.append((round(avg_start, 1), round(avg_end, 1), round(min(confidence, 1.0), 2)))

        return segments

    @staticmethod
    def _correlate_fingerprints(
        fp_a: list[int], fp_b: list[int], seconds_per_item: float
    ) -> tuple[float, float] | None:
        """
        Find the best matching segment between two fingerprint arrays using
        bit-level correlation with a sliding window.

        Returns (start_seconds, end_seconds) of the matching region, or None.
        """
        MIN_MATCH_LENGTH = 80  # ~10 seconds minimum match
        MATCH_THRESHOLD = 10   # Max differing bits per comparison (out of 32)
        # Window size for edge trimming: ~2.5 seconds
        TRIM_WINDOW = 20
        TRIM_DENSITY = 0.6  # Require 60% match density at edges

        best_offset = 0
        best_score = 0
        best_matches: list[bool] = []

        # Slide fp_b over fp_a
        max_offset = min(len(fp_a), len(fp_b)) - MIN_MATCH_LENGTH
        if max_offset <= 0:
            return None

        for offset in range(-max_offset, max_offset):
            a_start = max(0, offset)
            b_start = max(0, -offset)
            length = min(len(fp_a) - a_start, len(fp_b) - b_start)

            if length < MIN_MATCH_LENGTH:
                continue

            # Build match map for this offset
            match_map = []
            for k in range(length):
                diff = bin(fp_a[a_start + k] ^ fp_b[b_start + k]).count("1")
                match_map.append(diff <= MATCH_THRESHOLD)

            matches = sum(match_map)
            if matches >= MIN_MATCH_LENGTH and matches > best_score:
                best_score = matches
                best_offset = a_start
                best_matches = match_map

        if best_score < MIN_MATCH_LENGTH:
            return None

        # Trim edges where match density is too low
        start_idx = 0
        end_idx = len(best_matches) - 1

        # Trim from the start
        while start_idx < end_idx - MIN_MATCH_LENGTH:
            window_end = min(start_idx + TRIM_WINDOW, end_idx + 1)
            window = best_matches[start_idx:window_end]
            if sum(window) / len(window) >= TRIM_DENSITY:
                break
            start_idx += 1

        # Trim from the end
        while end_idx > start_idx + MIN_MATCH_LENGTH:
            window_start = max(end_idx - TRIM_WINDOW, start_idx)
            window = best_matches[window_start:end_idx + 1]
            if sum(window) / len(window) >= TRIM_DENSITY:
                break
            end_idx -= 1

        trimmed_matches = sum(best_matches[start_idx:end_idx + 1])
        if trimmed_matches < MIN_MATCH_LENGTH:
            return None

        start_sec = (best_offset + start_idx) * seconds_per_item
        end_sec = (best_offset + end_idx) * seconds_per_item
        return (start_sec, end_sec)

    async def _detect_outro(
        self, computing: ComputingService, file_path: str, duration: float
    ) -> float | None:
        """
        Detect outro/credits start using black frame detection on the last
        few minutes of an episode. Most TV episodes transition to credits
        with a brief black frame sequence.

        Returns the timestamp of the outro start, or None.
        """
        import os
        import re

        analysis_start = max(0, duration - OUTRO_ANALYSIS_DURATION)

        from pyrate.services.computing import build_media_volumes

        volumes = build_media_volumes(
            include_writable_temp=False,
            include_cache=False,
            include_downloads=False,
            read_only=True,
        )

        # blackdetect: detect black frames (>98% black pixels, min 0.1s duration).
        # Direct argv (no shell) — ``file_path`` is no longer interpolated into
        # an ``sh -c`` string, eliminating the previous injection vector.
        cmd = [
            "-ss", str(int(analysis_start)),
            "-t", str(int(duration - analysis_start)),
            "-i", file_path,
            "-vf", "blackdetect=d=0.1:pix_th=0.10:pic_th=0.98",
            "-an",
            "-f", "null",
            "-",
        ]

        try:
            import asyncio

            task_id = await computing.start_task(
                image=CHROMAPRINT_IMAGE,
                command=cmd,
                volumes=volumes,
                labels={"task": "blackdetect"},
            )

            for _ in range(60):
                status = await computing.get_task_status(task_id)
                if status in ("completed", "failed"):
                    break
                await asyncio.sleep(5)

            output = await computing.get_task_logs(task_id)
            await computing.delete_task(task_id)

            if not output:
                return None

            # Parse blackdetect output:
            # [blackdetect @ ...] black_start:1234.5 black_end:1235.0 black_duration:0.5
            black_events = re.findall(
                r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)\s+black_duration:\s*([\d.]+)",
                output,
            )

            if not black_events:
                return None

            # Look for the last significant black frame sequence in the final
            # portion of the episode. The outro typically starts at a black
            # transition in the last ~2 minutes.
            min_outro_time = duration - 180  # Outro should be in last 3 minutes
            for black_start_s, black_end_s, black_dur_s in reversed(black_events):
                black_start = float(black_start_s) + analysis_start
                black_dur = float(black_dur_s)
                # Accept black frames >= 0.2s as a scene transition
                if black_start >= min_outro_time and black_dur >= 0.2:
                    return black_start

            # Fallback: if no black frame in last 3 min, take the last one overall
            last_start = float(black_events[-1][0]) + analysis_start
            last_dur = float(black_events[-1][2])
            if last_dur >= 0.2 and last_start > duration - OUTRO_ANALYSIS_DURATION:
                return last_start

            return None

        except Exception as e:
            logger.error("Black frame detection error: %s", e)
            return None
