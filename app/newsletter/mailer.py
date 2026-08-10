"""SMTP message construction and delivery."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid


def build_message(
    *,
    subject: str,
    sender: str,
    recipient: str,
    text_body: str,
    html_body: str,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain="jobtracks.local")
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    return message


def send_message(
    message: EmailMessage,
    *,
    host: str,
    port: int,
    security: str,
    username: str | None,
    password: str | None,
    timeout: float = 20,
) -> None:
    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if security == "ssl" else smtplib.SMTP
    with smtp_class(host=host, port=port, timeout=timeout) as smtp:
        if security == "starttls":
            smtp.starttls(context=context)
        if username:
            smtp.login(username, password or "")
        smtp.send_message(message)

