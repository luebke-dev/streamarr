"""
Email Service

This service handles sending emails using Jinja2 templates.
"""

import html as _html
import logging
from pathlib import Path

import emails
from jinja2 import Environment, FileSystemLoader, select_autoescape

from pyrate.config import get_app_url, settings

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails with Jinja2 templates"""

    def __init__(self):
        self.config = settings.email
        self.jinja_env = None
        self._initialize_jinja()

    def _initialize_jinja(self):
        """Initialize Jinja2 environment for email templates"""
        # Path calculation: backend/src/pyrate/services -> backend/templates/email
        # In Docker, this is /app/src/pyrate/services -> /app/templates/email
        templates_path = (
            Path(__file__).parent.parent.parent.parent / self.config.templates_dir
        )
        if not templates_path.exists():
            logger.warning("Email templates directory not found: %s. ", templates_path)
            # Don't try to create the directory in production, just log the warning
            self.jinja_env = None
            return

        self.jinja_env = Environment(
            loader=FileSystemLoader(str(templates_path)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def render_template(self, template_name: str, context: dict) -> tuple[str, str]:
        """
        Render email template with context

        Args:
            template_name: Name of the template file (without extension)
            context: Dictionary with template variables

        Returns:
            Tuple of (html_content, text_content)
        """
        if not self.jinja_env:
            # Templates not available, return empty strings
            logger.warning(
                "Jinja environment not initialized. Cannot render templates."
            )
            return "", context.get("message", "")

        # Try to load HTML template
        html_content = ""
        try:
            html_template = self.jinja_env.get_template(f"{template_name}.html")
            html_content = html_template.render(**context)
        except Exception as e:
            logger.warning("Failed to load HTML template %s.html: %s", template_name, e)

        # Try to load text template
        text_content = ""
        try:
            text_template = self.jinja_env.get_template(f"{template_name}.txt")
            text_content = text_template.render(**context)
        except Exception as e:
            logger.warning("Failed to load text template %s.txt: %s", template_name, e)
            # Fallback to simple text version if HTML exists
            if html_content:
                text_content = context.get("message", "")

        return html_content, text_content

    async def send_email(
        self,
        to_email: str,
        subject: str,
        message: str = "",
        template_name: str | None = None,
        context: dict | None = None,
        html_content: str | None = None,
    ) -> bool:
        """
        Send an email

        Args:
            to_email: Recipient email address
            subject: Email subject
            message: Plain text message (used if no template)
            template_name: Name of template to use (optional)
            context: Template context variables (optional)
            html_content: Direct HTML content (optional, overrides template)

        Returns:
            True if email was sent successfully, False otherwise
        """
        if not self.config.enabled:
            logger.info("Email not sent to %s (email system disabled): %s", to_email, subject)
            return False

        try:
            # Prepare email content
            if template_name and context:
                html_body, text_body = self.render_template(template_name, context)
            elif html_content:
                html_body = html_content
                text_body = message or ""
            else:
                # HTML-escape ``message`` so user-supplied text can't inject
                # markup into the fallback body. The Jinja template paths
                # above already escape via ``select_autoescape``.
                html_body = f"<html><body><p>{_html.escape(message or '')}</p></body></html>"
                text_body = message

            # Build email
            email_message = emails.Message(
                subject=subject,
                html=html_body,
                text=text_body,
                mail_from=(self.config.from_name, self.config.from_email),
            )

            # Add reply-to if configured
            if self.config.reply_to:
                email_message.set_header("Reply-To", self.config.reply_to)

            # Send email
            smtp_config = {
                "host": self.config.smtp_host,
                "port": self.config.smtp_port,
                "tls": self.config.smtp_use_tls,
                "ssl": self.config.smtp_use_ssl,
            }

            if self.config.smtp_user and self.config.smtp_password:
                smtp_config["user"] = self.config.smtp_user
                smtp_config["password"] = self.config.smtp_password

            response = email_message.send(to=to_email, smtp=smtp_config)

            if response.status_code in (250, 200):
                logger.info("Email sent successfully to %s: %s", to_email, subject)
                return True
            else:
                logger.error(
                    "Failed to send email to %s: %s - %s",
                    to_email, response.status_code, response.error,
                )
                return False

        except Exception as e:
            logger.error("Error sending email to %s: %s", to_email, e)
            return False

    async def send_notification_email(
        self,
        to_email: str,
        subject: str,
        message: str,
        notification_type: str = "info",
        i18n: dict[str, str] | None = None,
        lang: str = "en",
        app_name: str = "Pyrate Media",
    ) -> bool:
        """
        Send a notification email using the default notification template

        Args:
            to_email: Recipient email address
            subject: Email subject
            message: Notification message
            notification_type: Type of notification (info, warning, error, success)
            i18n: Internationalized strings for the template
            lang: Language code (e.g. "en", "de")
            app_name: Application name

        Returns:
            True if email was sent successfully, False otherwise
        """
        if i18n is None:
            i18n = {
                "footer": f"This email was sent automatically by {app_name}.",
                "ignore_hint": "If you did not request this email, you can safely ignore it.",
            }

        context = {
            "subject": subject,
            "message": message,
            "notification_type": notification_type,
            "app_name": app_name,
            "app_url": get_app_url(),
            "lang": lang,
            "i18n": i18n,
        }

        return await self.send_email(
            to_email=to_email,
            subject=subject,
            message=message,
            template_name="notification",
            context=context,
        )


# Global email service instance
email_service = EmailService()
