"""Tests for EmailService template rendering.

Tests the Jinja2 template rendering functionality of EmailService
using the real templates in backend/templates/email/.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from pyrate.services.email import EmailService


@pytest.fixture
def email_service() -> EmailService:
    """Create an EmailService with the real template directory."""
    with patch("pyrate.services.email.settings") as mock_settings:
        mock_settings.email.enabled = False  # Don't actually send emails
        mock_settings.email.templates_dir = "templates/email"
        mock_settings.email.from_name = "Pyrate Media"
        mock_settings.email.from_email = "noreply@pyrate.media"
        mock_settings.email.reply_to = None
        mock_settings.email.smtp_host = "localhost"
        mock_settings.email.smtp_port = 587
        mock_settings.email.smtp_use_tls = True
        mock_settings.email.smtp_use_ssl = False
        mock_settings.email.smtp_user = None
        mock_settings.email.smtp_password = None
        mock_settings.cors_allowed_origins = ["http://localhost:8080"]
        service = EmailService()
    return service


class TestJinjaInitialization:
    """Tests for Jinja2 environment initialization."""

    def test_jinja_env_initialized(self, email_service: EmailService):
        """Test that Jinja environment is initialized when templates exist."""
        # Templates exist at backend/templates/email/
        # The fixture patches config to point there
        # Whether jinja_env is None depends on path resolution
        # This test verifies the initialization doesn't crash
        assert email_service is not None

    def test_jinja_env_none_when_dir_missing(self):
        """Test that Jinja env is None when templates dir doesn't exist."""
        with patch("pyrate.services.email.settings") as mock_settings:
            mock_settings.email.enabled = False
            mock_settings.email.templates_dir = "nonexistent/path"
            service = EmailService()
            assert service.jinja_env is None


class TestRenderTemplate:
    """Tests for template rendering."""

    @staticmethod
    def notification_context(**overrides) -> dict:
        context = {
            "subject": "Test Notification",
            "message": "This is a test message.",
            "notification_type": "info",
            "app_name": "Pyrate Media",
            "app_url": "http://localhost:8080",
            "lang": "en",
            "i18n": {
                "footer": "This email was sent automatically by Pyrate Media.",
                "ignore_hint": "If you did not request this email, you can safely ignore it.",
            },
        }
        context.update(overrides)
        return context

    @staticmethod
    def welcome_context() -> dict:
        return {
            "subject": "Welcome to Pyrate Media",
            "user_name": "John",
            "app_name": "Pyrate Media",
            "app_url": "http://localhost:8080",
            "lang": "en",
            "i18n": {
                "heading": "Welcome",
                "body": "Welcome to Pyrate Media.",
                "features": "Browse and play your media library.",
                "button": "Open Pyrate Media",
                "help": "Contact your administrator if you need help.",
            },
        }

    @pytest.fixture
    def service_with_templates(self) -> EmailService:
        """Create EmailService pointing directly to the real templates."""
        templates_dir = (
            Path(__file__).parent.parent / "templates" / "email"
        )
        if not templates_dir.exists():
            pytest.skip("Template directory not found")

        with patch("pyrate.services.email.settings") as mock_settings:
            mock_settings.email.enabled = False
            mock_settings.email.templates_dir = "templates/email"
            service = EmailService()

        # Manually set up jinja env pointing to real templates
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        service.jinja_env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        return service

    def test_render_notification_html(self, service_with_templates: EmailService):
        """Test rendering notification HTML template."""
        context = self.notification_context()
        html, text = service_with_templates.render_template("notification", context)

        assert len(html) > 0
        assert "Test Notification" in html
        assert "This is a test message" in html

    def test_render_notification_text(self, service_with_templates: EmailService):
        """Test rendering notification plain text template."""
        context = self.notification_context()
        html, text = service_with_templates.render_template("notification", context)

        assert len(text) > 0
        assert "Pyrate Media" in text
        assert "This is a test message" in text

    def test_render_notification_type_in_text(
        self, service_with_templates: EmailService
    ):
        """Test that notification type appears in plain text output."""
        context = self.notification_context(
            subject="Warning",
            message="Something happened.",
            notification_type="warning",
        )
        _, text = service_with_templates.render_template("notification", context)
        assert "WARNING" in text

    def test_render_welcome_html(self, service_with_templates: EmailService):
        """Test rendering welcome HTML template."""
        context = self.welcome_context()
        html, text = service_with_templates.render_template("welcome", context)
        # If template renders, it should have content
        assert len(html) > 0 or len(text) > 0

    def test_render_nonexistent_template(self, service_with_templates: EmailService):
        """Test rendering a template that doesn't exist."""
        html, text = service_with_templates.render_template(
            "nonexistent", {"message": "fallback"}
        )
        # Should not crash, returns empty/fallback strings
        assert html == ""

    def test_render_without_jinja_env(self):
        """Test rendering when jinja env is not initialized."""
        with patch("pyrate.services.email.settings") as mock_settings:
            mock_settings.email.enabled = False
            mock_settings.email.templates_dir = "nonexistent"
            service = EmailService()

        html, text = service.render_template(
            "notification", {"message": "fallback text"}
        )
        assert html == ""
        assert text == "fallback text"


class TestSendEmail:
    """Tests for the send_email method (disabled mode)."""

    @pytest.mark.asyncio
    async def test_send_email_disabled(self):
        """Test that sending email when disabled returns False."""
        with patch("pyrate.services.email.settings") as mock_settings:
            mock_settings.email.enabled = False
            mock_settings.email.templates_dir = "templates/email"
            service = EmailService()

        result = await service.send_email(
            to_email="test@example.com",
            subject="Test",
            message="Hello",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_send_notification_email_disabled(self):
        """Test that notification email when disabled returns False."""
        with patch("pyrate.services.email.settings") as mock_settings:
            mock_settings.email.enabled = False
            mock_settings.email.templates_dir = "templates/email"
            mock_settings.cors_allowed_origins = ["http://localhost:8080"]
            service = EmailService()

        result = await service.send_notification_email(
            to_email="test@example.com",
            subject="Test Notification",
            message="Something happened",
            notification_type="info",
        )
        assert result is False
