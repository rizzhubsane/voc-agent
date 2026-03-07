"""
Slack Integration Helper.
Sends direct messages via the Slack Web API.
"""

import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

def send_slack_message(text: str) -> bool:
    """
    Sends a text message as a Direct Message (or to a channel) using the Slack Web API.
    Requires SLACK_BOT_TOKEN and SLACK_USER_ID (or channel ID) in .env.
    
    Args:
        text (str): The markdown or plain text message to send.
        
    Returns:
        bool: True if sent successfully, False on error or if misconfigured.
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    user_id = os.getenv("SLACK_USER_ID")  # Can be a user ID (U1234) or channel ID (C1234)
    
    # Fallback to the old webhook method if they are still using that
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    
    if not token or not user_id:
        if webhook_url:
            logger.info("Using legacy Webhook URL for Slack since Bot Token / User ID is missing.")
            return _send_via_webhook(webhook_url, text)
            
        logger.info("SLACK_BOT_TOKEN or SLACK_USER_ID not configured. Skipping Slack notification.")
        return False
        
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    payload = {
        "channel": user_id,
        "text": text
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if not data.get("ok"):
            logger.error(f"Slack API error: {data.get('error')}")
            return False
            
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Slack message: {e}")
        return False


def _send_via_webhook(webhook_url: str, text: str) -> bool:
    """Legacy helper for fallback."""
    try:
        response = requests.post(
            webhook_url,
            json={"text": text},
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Slack Webhook message: {e}")
        return False
