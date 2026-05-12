"""
Email Manager — send email via SMTP, read recent via IMAP.
Configurable accounts stored in settings.
"""

import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.header import decode_header
from typing import Optional


class EmailManager:

    @staticmethod
    def send(to: str, subject: str, body: str,
             smtp_server: str = None, smtp_port: int = None,
             username: str = None, password: str = None,
             from_address: str = None) -> dict:
        """Send an email via SMTP."""
        if not all([to, subject, body, smtp_server, username, password]):
            return {"success": False, "message": "Missing required email configuration"}
        smtp_port = smtp_port or 587
        from_address = from_address or username
        try:
            msg = MIMEText(body, "plain")
            msg["Subject"] = subject
            msg["From"] = from_address
            msg["To"] = to

            with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)

            return {"success": True, "message": f"Email sent to {to}"}
        except smtplib.SMTPAuthenticationError:
            return {"success": False, "message": "SMTP authentication failed. Check username/password."}
        except smtplib.SMTPRecipientsRefused:
            return {"success": False, "message": f"Recipient refused: {to}"}
        except smtplib.SMTPException as e:
            return {"success": False, "message": f"SMTP error: {e}"}
        except OSError as e:
            return {"success": False, "message": f"Connection error: {e}"}
        except Exception as e:
            return {"success": False, "message": f"Email send failed: {e}"}

    @staticmethod
    def send_from_settings(to: str, subject: str, body: str) -> dict:
        """Send email using credentials from Plia settings."""
        from core.settings_store import settings
        config = {
            "smtp_server": settings.get("email.smtp_server", ""),
            "smtp_port": settings.get("email.smtp_port", 587),
            "username": settings.get("email.username", ""),
            "password": settings.get("email.password", ""),
            "from_address": settings.get("email.from_address", ""),
        }
        return EmailManager.send(to, subject, body, **config)

    @staticmethod
    def read_recent(imap_server: str = None, imap_port: int = None,
                    username: str = None, password: str = None,
                    limit: int = 10) -> dict:
        """Read recent emails from IMAP inbox."""
        if not all([imap_server, username, password]):
            return {"success": False, "message": "Missing required IMAP configuration"}
        imap_port = imap_port or 993
        limit = max(1, min(limit, 50))

        try:
            with imaplib.IMAP4_SSL(imap_server, imap_port, timeout=15) as mail:
                mail.login(username, password)
                mail.select("INBOX")

                status, messages = mail.search(None, "ALL")
                if status != "OK":
                    return {"success": False, "message": "Could not search inbox"}

                msg_ids = messages[0].split()
                if not msg_ids:
                    return {"success": True, "message": "Inbox is empty", "emails": []}

                recent_ids = msg_ids[-limit:]

                emails = []
                for msg_id in recent_ids:
                    status, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if status != "OK":
                        continue
                    raw_email = msg_data[0][1]
                    parsed = EmailManager._parse_email(raw_email)
                    if parsed:
                        emails.append(parsed)

                return {
                    "success": True,
                    "message": f"Found {len(emails)} recent emails",
                    "emails": emails,
                    "total_in_inbox": len(msg_ids),
                }
        except imaplib.IMAP4.error as e:
            return {"success": False, "message": f"IMAP error: {e}"}
        except OSError as e:
            return {"success": False, "message": f"Connection error: {e}"}
        except Exception as e:
            return {"success": False, "message": f"Email read failed: {e}"}

    @staticmethod
    def read_recent_from_settings(limit: int = 10) -> dict:
        """Read recent emails using credentials from Plia settings."""
        from core.settings_store import settings
        config = {
            "imap_server": settings.get("email.imap_server", ""),
            "imap_port": settings.get("email.imap_port", 993),
            "username": settings.get("email.username", ""),
            "password": settings.get("email.password", ""),
        }
        return EmailManager.read_recent(limit=limit, **config)

    @staticmethod
    def _parse_email(raw_bytes: bytes) -> Optional[dict]:
        """Parse raw email bytes into a structured dict."""
        try:
            msg = email.message_from_bytes(raw_bytes)
            subject = EmailManager._decode_header_value(msg.get("Subject", "(No Subject)"))
            from_ = EmailManager._decode_header_value(msg.get("From", "(Unknown)"))
            date = msg.get("Date", "")

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            try:
                                body = payload.decode("utf-8", errors="replace")
                            except (LookupError, UnicodeDecodeError):
                                body = payload.decode("latin-1", errors="replace")
                        break
                    elif content_type == "text/html" and not body:
                        payload = part.get_payload(decode=True)
                        if payload:
                            try:
                                body = payload.decode("utf-8", errors="replace")
                            except (LookupError, UnicodeDecodeError):
                                body = payload.decode("latin-1", errors="replace")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    try:
                        body = payload.decode("utf-8", errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        body = payload.decode("latin-1", errors="replace")

            return {
                "subject": subject[:200],
                "from": from_[:200],
                "date": date,
                "body_preview": body[:500].strip(),
            }
        except Exception:
            return None

    @staticmethod
    def _decode_header_value(value: str) -> str:
        """Decode encoded email headers (e.g. =?UTF-8?B?...?=)."""
        if not value:
            return ""
        try:
            decoded_parts = decode_header(value)
            result = []
            for part, charset in decoded_parts:
                if isinstance(part, bytes):
                    try:
                        result.append(part.decode(charset or "utf-8", errors="replace"))
                    except (LookupError, UnicodeDecodeError):
                        result.append(part.decode("latin-1", errors="replace"))
                else:
                    result.append(str(part))
            return " ".join(result)
        except Exception:
            return str(value)

    @staticmethod
    def test_connection(smtp_server: str = None, smtp_port: int = None,
                        imap_server: str = None, imap_port: int = None,
                        username: str = None, password: str = None) -> dict:
        """Test SMTP and IMAP connections with given credentials."""
        results = {}
        if smtp_server and username and password:
            try:
                with smtplib.SMTP(smtp_server, smtp_port or 587, timeout=10) as server:
                    server.starttls()
                    server.login(username, password)
                    results["smtp"] = "OK"
            except Exception as e:
                results["smtp"] = str(e)
        if imap_server and username and password:
            try:
                with imaplib.IMAP4_SSL(imap_server, imap_port or 993, timeout=10) as mail:
                    mail.login(username, password)
                    results["imap"] = "OK"
            except Exception as e:
                results["imap"] = str(e)
        return results


email_manager = EmailManager()
