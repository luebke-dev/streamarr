"""Tests for streamarr.api.dependencies module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from streamarr.api.dependencies import get_payment_provider, get_payment_service


class TestGetPaymentProvider:
    def test_payment_disabled(self):
        with patch("streamarr.api.dependencies.settings") as mock_settings:
            mock_settings.payment.enabled = False
            result = get_payment_provider()
            assert result is None

    def test_payment_stripe(self):
        with patch("streamarr.api.dependencies.settings") as mock_settings:
            mock_settings.payment.enabled = True
            mock_settings.payment.provider = "stripe"
            mock_settings.payment.stripe_secret_key = "sk_test_xxx"
            mock_settings.payment.stripe_publishable_key = "pk_test_xxx"
            mock_settings.payment.stripe_webhook_secret = "whsec_xxx"

            try:
                result = get_payment_provider()
                assert result is not None
            except ModuleNotFoundError:
                # stripe package not installed in test environment; verify the
                # code path reaches the import by confirming it tried
                pytest.skip("stripe package not installed")

    def test_payment_unknown_provider(self):
        with patch("streamarr.api.dependencies.settings") as mock_settings:
            mock_settings.payment.enabled = True
            mock_settings.payment.provider = "unknown_provider"
            result = get_payment_provider()
            assert result is None


class TestGetPaymentService:
    @pytest.mark.asyncio
    async def test_provider_none(self):
        mock_db = AsyncMock()
        result = await get_payment_service(db=mock_db, provider=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_provider_present(self):
        mock_db = AsyncMock()
        mock_provider = MagicMock()
        result = await get_payment_service(db=mock_db, provider=mock_provider)
        assert result is not None
        from streamarr.services.payment import PaymentService

        assert isinstance(result, PaymentService)
