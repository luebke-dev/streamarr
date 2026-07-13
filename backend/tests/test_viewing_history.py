"""Tests for ViewingHistory model logic."""

import pytest

from streamarr.models.viewing_history import ViewingHistory


class TestCalculateProgressPercentage:
    """Tests for the progress percentage calculation."""

    def test_zero_progress(self):
        """Test 0% progress."""
        vh = ViewingHistory()
        vh.progress_seconds = 0
        vh.duration_seconds = 3600
        assert vh.calculate_progress_percentage() == 0.0

    def test_half_progress(self):
        """Test 50% progress."""
        vh = ViewingHistory()
        vh.progress_seconds = 1800
        vh.duration_seconds = 3600
        result = vh.calculate_progress_percentage()
        assert abs(result - 50.0) < 0.01

    def test_full_progress(self):
        """Test 100% progress."""
        vh = ViewingHistory()
        vh.progress_seconds = 3600
        vh.duration_seconds = 3600
        assert vh.calculate_progress_percentage() == 100.0

    def test_capped_at_100(self):
        """Test that progress is capped at 100%."""
        vh = ViewingHistory()
        vh.progress_seconds = 5000
        vh.duration_seconds = 3600
        assert vh.calculate_progress_percentage() == 100.0

    def test_zero_duration(self):
        """Test with zero duration returns 0%."""
        vh = ViewingHistory()
        vh.progress_seconds = 100
        vh.duration_seconds = 0
        assert vh.calculate_progress_percentage() == 0.0

    def test_none_duration(self):
        """Test with None duration returns 0%."""
        vh = ViewingHistory()
        vh.progress_seconds = 100
        vh.duration_seconds = None
        assert vh.calculate_progress_percentage() == 0.0

    def test_small_progress(self):
        """Test small progress percentage."""
        vh = ViewingHistory()
        vh.progress_seconds = 60
        vh.duration_seconds = 7200  # 2 hours
        result = vh.calculate_progress_percentage()
        assert abs(result - (60 / 7200 * 100)) < 0.01


class TestUpdateProgress:
    """Tests for the update_progress method."""

    def test_update_progress_basic(self):
        """Test basic progress update."""
        vh = ViewingHistory()
        vh.duration_seconds = 3600
        vh.is_completed = False

        vh.update_progress(1800)

        assert vh.progress_seconds == 1800
        assert abs(vh.progress_percentage - 50.0) < 0.01
        assert vh.is_completed is False

    def test_update_progress_with_duration(self):
        """Test progress update that also sets duration."""
        vh = ViewingHistory()
        vh.duration_seconds = None
        vh.is_completed = False

        vh.update_progress(900, duration_seconds=3600)

        assert vh.progress_seconds == 900
        assert vh.duration_seconds == 3600
        assert abs(vh.progress_percentage - 25.0) < 0.01

    def test_auto_complete_above_90(self):
        """Test that content is auto-completed when progress > 90%."""
        vh = ViewingHistory()
        vh.duration_seconds = 3600
        vh.is_completed = False

        vh.update_progress(3300)  # 91.67%

        assert vh.is_completed is True

    def test_auto_complete_exactly_91(self):
        """Test auto-complete at exactly > 90%."""
        vh = ViewingHistory()
        vh.duration_seconds = 1000
        vh.is_completed = False

        vh.update_progress(901)  # 90.1%

        assert vh.is_completed is True

    def test_not_completed_at_90(self):
        """Test that 90% exactly does not trigger completion."""
        vh = ViewingHistory()
        vh.duration_seconds = 1000
        vh.is_completed = False

        vh.update_progress(900)  # exactly 90%

        assert vh.is_completed is False

    def test_reset_completed_below_85(self):
        """Test that completed status is reset when seeking back below 85%."""
        vh = ViewingHistory()
        vh.duration_seconds = 1000
        vh.is_completed = True

        vh.update_progress(840)  # 84%

        assert vh.is_completed is False

    def test_keep_completed_between_85_and_90(self):
        """Test that completed status is kept between 85-90%."""
        vh = ViewingHistory()
        vh.duration_seconds = 1000
        vh.is_completed = True

        vh.update_progress(870)  # 87%

        # Between 85% and 90%, is_completed stays True (not reset)
        assert vh.is_completed is True

    def test_progress_percentage_updated(self):
        """Test that progress_percentage field is updated."""
        vh = ViewingHistory()
        vh.duration_seconds = 3600
        vh.progress_percentage = 0.0
        vh.is_completed = False

        vh.update_progress(1800)

        assert abs(vh.progress_percentage - 50.0) < 0.01

    def test_multiple_updates(self):
        """Test sequential progress updates."""
        vh = ViewingHistory()
        vh.duration_seconds = 1000
        vh.is_completed = False

        # Watch to 50%
        vh.update_progress(500)
        assert vh.is_completed is False
        assert abs(vh.progress_percentage - 50.0) < 0.01

        # Watch to 95% -> auto-complete
        vh.update_progress(950)
        assert vh.is_completed is True

        # Seek back to 20% -> reset
        vh.update_progress(200)
        assert vh.is_completed is False

        # Watch to 92% again -> auto-complete again
        vh.update_progress(920)
        assert vh.is_completed is True
