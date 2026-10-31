"""SMTP delivery and encrypted per-account credentials."""
import os
import smtplib
import ssl
from email.message import EmailMessage
from cryptography.fernet import Fernet, InvalidToken


def cipher():
    key = os.getenv('SMTP_ENCRYPTION_KEY', '').strip()
    if not key:
        raise ValueError('SMTP_ENCRYPTION_KEY is required to save SMTP credentials')
    try:
        return Fernet(key.encode('ascii'))
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid SMTP_ENCRYPTION_KEY') from exc


def encrypt_secret(value: str) -> str:
    return cipher().encrypt(value.encode('utf-8')).decode('ascii')


def decrypt_secret(value: str) -> str:
    try:
        return cipher().decrypt(value.encode('ascii')).decode('utf-8')
    except InvalidToken as exc:
        raise ValueError('Could not decrypt SMTP credentials; check SMTP_ENCRYPTION_KEY') from exc


def send_email(settings, recipient: str, subject: str, body: str):
    if settings.smtp_security not in {'starttls', 'ssl'}:
        raise ValueError('Unsupported SMTP security mode')
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = settings.from_email
    message['To'] = recipient
    message.set_content(body)
    port = settings.smtp_port
    host = settings.smtp_host
    context = ssl.create_default_context()
    if settings.smtp_security == 'ssl':
        connection = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
    else:
        connection = smtplib.SMTP(host, port, timeout=15)
    with connection as smtp:
        if settings.smtp_security == 'starttls':
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        if settings.smtp_username:
            if not settings.smtp_password_encrypted:
                raise ValueError('SMTP password missing')
            smtp.login(settings.smtp_username, decrypt_secret(settings.smtp_password_encrypted))
        smtp.send_message(message)
