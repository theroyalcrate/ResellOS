"""
One-time OAuth setup for Agent 1B (Gmail + Drive).
Run this once to generate credentials/token.json.

Before running:
  1. Download your OAuth client secrets from Google Cloud Console
  2. Save the file as credentials/credentials.json
  3. Run: python setup_oauth.py
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/drive',
]

CREDENTIALS_DIR = os.path.join(os.path.dirname(__file__), 'credentials')
CREDENTIALS_PATH = os.path.join(CREDENTIALS_DIR, 'credentials.json')
TOKEN_PATH = os.path.join(CREDENTIALS_DIR, 'token.json')


def main():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    print("Success! token.json saved to", TOKEN_PATH)


if __name__ == '__main__':
    main()
