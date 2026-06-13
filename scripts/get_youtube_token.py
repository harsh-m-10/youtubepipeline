"""One-time local OAuth flow to mint a YouTube refresh token.

1. Google Cloud Console -> create project -> enable "YouTube Data API v3"
2. OAuth consent screen -> External -> add yourself as a test user
3. Credentials -> Create OAuth client ID -> Desktop app -> download JSON
4. Run:  python scripts/get_youtube_token.py path/to/client_secret.json
5. Put the printed values into GitHub repo secrets:
   YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN

Note: while the OAuth app is in "Testing" mode, refresh tokens expire after
7 days. Publish the consent screen (no verification needed for personal use
with the upload scope on your own account) to make the token long-lived.
"""

import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    secrets_file = sys.argv[1]
    flow = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    client = json.load(open(secrets_file))["installed"]
    print("\nAdd these as GitHub repo secrets:\n")
    print(f"YT_CLIENT_ID={client['client_id']}")
    print(f"YT_CLIENT_SECRET={client['client_secret']}")
    print(f"YT_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
