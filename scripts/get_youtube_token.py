"""One-time local OAuth flow to mint a YouTube refresh token.

Two ways to run:
  A) Re-auth with the EXISTING app (easiest — uses YT_CLIENT_ID/SECRET from .env,
     no file needed):   python scripts/get_youtube_token.py
  B) Fresh app from a downloaded client secret:
     python scripts/get_youtube_token.py path/to/client_secret.json

Then update the YT_REFRESH_TOKEN GitHub secret AND your local .env with the
printed value (client id/secret are unchanged on a re-auth).

First-time setup for (B): Google Cloud Console -> enable "YouTube Data API v3"
and "YouTube Analytics API" -> OAuth consent screen (External, add yourself as a
test user) -> Credentials -> OAuth client ID (Desktop app) -> download JSON.

Note: while the OAuth app is in "Testing" mode, refresh tokens expire after
7 days. Publish the consent screen (no verification needed for personal use on
your own account) to make the token long-lived.
"""

import json
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

# must match src/publish/youtube.py SCOPES (upload + comments + analytics)
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def main() -> None:
    if len(sys.argv) == 2:  # mode B: from downloaded client secret file
        secrets_file = sys.argv[1]
        flow = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES)
        client = json.load(open(secrets_file))["installed"]
        cid, csecret = client["client_id"], client["client_secret"]
    else:  # mode A: re-auth using existing credentials from .env
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        cid = os.getenv("YT_CLIENT_ID")
        csecret = os.getenv("YT_CLIENT_SECRET")
        if not (cid and csecret):
            print("YT_CLIENT_ID / YT_CLIENT_SECRET not found in env.\n")
            print(__doc__)
            sys.exit(1)
        flow = InstalledAppFlow.from_client_config(
            {"installed": {
                "client_id": cid,
                "client_secret": csecret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }},
            SCOPES,
        )

    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    print("\nUpdate YT_REFRESH_TOKEN in the GitHub repo secret AND your local .env:\n")
    print(f"YT_CLIENT_ID={cid}")
    print(f"YT_CLIENT_SECRET={csecret}")
    print(f"YT_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
