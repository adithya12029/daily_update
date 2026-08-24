"""
notifier.py

Builds a modern, mobile-friendly HTML email digest and sends it via
Gmail's SMTP server using an App Password over SSL (port 465).
"""

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import List

from config import (
    EMAIL_SUBJECT_PREFIX,
    GMAIL_APP_PASSWORD,
    GMAIL_USER,
    RECIPIENT_EMAIL,
    SMTP_HOST,
    SMTP_PORT,
)
from summarizer import CuratedStory


def _render_story_card(story: CuratedStory) -> str:
    """
    Render a single curated story as an HTML "card" block.

    Args:
        story: The curated story to render.

    Returns:
        An HTML string for the story card. All text is HTML-escaped to
        prevent markup injection from article titles/summaries.
    """
    topic = escape(story["topic"])
    title = escape(story["title"])
    url = escape(story["url"], quote=True)
    source = escape(story["source"])
    summary = escape(story["summary"])

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="background-color:#ffffff; border-radius:12px; margin-bottom:16px;
                  box-shadow:0 1px 3px rgba(0,0,0,0.08); overflow:hidden;">
      <tr>
        <td style="padding:20px 24px;">
          <div style="display:inline-block; background-color:#eef2ff; color:#4338ca;
                      font-size:12px; font-weight:600; letter-spacing:0.03em;
                      text-transform:uppercase; padding:4px 10px; border-radius:999px;
                      margin-bottom:10px;">
            {topic}
          </div>
          <h2 style="margin:8px 0 8px 0; font-size:18px; line-height:1.4; color:#111827;
                     font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
            <a href="{url}" style="color:#111827; text-decoration:none;">{title}</a>
          </h2>
          <p style="margin:0 0 12px 0; font-size:14px; line-height:1.6; color:#4b5563;
                    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
            {summary}
          </p>
          <div style="font-size:12px; color:#9ca3af; margin-bottom:12px;
                      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
            Source: {source}
          </div>
          <a href="{url}"
             style="display:inline-block; background-color:#4338ca; color:#ffffff;
                    text-decoration:none; font-size:13px; font-weight:600;
                    padding:9px 16px; border-radius:8px;
                    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
            Read full story &rarr;
          </a>
        </td>
      </tr>
    </table>
    """


def build_html_digest(stories: List[CuratedStory]) -> str:
    """
    Build a full, mobile-friendly HTML email document from curated stories.

    Args:
        stories: The list of curated stories to include.

    Returns:
        A complete HTML document as a string.
    """
    date_str = datetime.now().strftime("%A, %B %d, %Y")
    cards_html = "\n".join(_render_story_card(story) for story in stories)

    if not stories:
        cards_html = """
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding:24px; text-align:center; color:#6b7280;
                       font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
              No new, non-duplicate stories were found today.
            </td>
          </tr>
        </table>
        """

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Daily News Digest</title>
</head>
<body style="margin:0; padding:0; background-color:#f3f4f6;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f6; padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px; width:100%;">
          <tr>
            <td style="padding:8px 16px 24px 16px; text-align:center;">
              <h1 style="margin:0; font-size:22px; color:#111827;
                         font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
                🗞️ Your Daily News Digest
              </h1>
              <p style="margin:6px 0 0 0; font-size:13px; color:#6b7280;
                        font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
                {date_str}
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:0 16px;">
              {cards_html}
            </td>
          </tr>
          <tr>
            <td style="padding:16px; text-align:center;">
              <p style="margin:0; font-size:11px; color:#9ca3af;
                        font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
                Automatically curated and delivered by your News Agent.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def send_digest_email(stories: List[CuratedStory]) -> None:
    """
    Send the HTML news digest to the configured recipient via Gmail SMTP.

    Args:
        stories: The list of curated stories to include in the email.

    Raises:
        RuntimeError: If authentication or sending fails for any reason.
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    subject = f"{EMAIL_SUBJECT_PREFIX} — {date_str}"

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = GMAIL_USER
    message["To"] = RECIPIENT_EMAIL

    plain_fallback = (
        "\n\n".join(
            f"[{s['topic']}] {s['title']}\n{s['summary']}\n{s['url']}" for s in stories
        )
        or "No new stories today."
    )

    message.attach(MIMEText(plain_fallback, "plain"))
    message.attach(MIMEText(build_html_digest(stories), "html"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, [RECIPIENT_EMAIL], message.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            "Gmail authentication failed. Ensure GMAIL_USER and "
            "GMAIL_APP_PASSWORD are correct and that you are using a "
            "16-character App Password, not your normal account password."
        ) from exc
    except smtplib.SMTPException as exc:
        raise RuntimeError(f"Failed to send digest email via SMTP: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Unexpected error sending digest email: {exc}") from exc
if __name__ == "__main__":
    print("1. Preparing mock curated stories...")
    sample_stories: List[CuratedStory] = [
        {
            "topic": "AI Security",
            "title": "Why most organizations are getting AI security wrong",
            "source": "TechRadar",
            "summary": "Many organizations are reportedly failing to implement effective AI security measures. This widespread oversight is predicted to lead to significant negative consequences as AI adoption grows.",
            "url": "https://techradar.com"
        },
        {
            "topic": "AI Governance",
            "title": "Singapore Abandons Voluntary AI Governance Framework",
            "source": "Tech Times",
            "summary": "Singapore is shifting its approach to AI governance from a voluntary model to binding legislation. The change aims to make compliance mandatory across platforms.",
            "url": "https://techtimes.com"
        }
    ]

    print("2. Generating and saving local HTML preview (email_preview.html)...")
    html_content = build_html_digest(sample_stories)
    with open("email_preview.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("   -> Saved 'email_preview.html'. Open this file in your browser to inspect the layout!")

    print(f"\n3. Attempting to send test email to {RECIPIENT_EMAIL}...")
    try:
        send_digest_email(sample_stories)
        print("   -> Email sent successfully! Check your inbox (and Spam folder).")
    except Exception as e:
        print(f"   -> Failed to send email: {e}")