"""One-time local flow to mint an Instagram long-lived access token.

Prerequisites:
1. Instagram app -> Settings -> Account type -> switch to Professional (Creator). Free.
2. developers.facebook.com -> Create app -> "Other" / "Business" -> add the
   product "Instagram" -> "Instagram API with Instagram Login" (NO Facebook Page
   needed for this variant).
3. In that product's settings, under "Business login settings":
   - Add an OAuth redirect URI:  https://localhost:8443/
   - Copy the "Instagram app ID" and "Instagram app secret".

Run:
    python scripts/get_instagram_token.py <INSTAGRAM_APP_ID> <INSTAGRAM_APP_SECRET>

It opens the consent page, captures the redirect code, exchanges it for a
short-lived then a long-lived (60-day) token, and prints:
    IG_USER_ID, IG_ACCESS_TOKEN
Put both into .env and GitHub secrets.
"""

import http.server
import socket
import ssl
import sys
import urllib.parse
import webbrowser

import requests

REDIRECT = "https://localhost:8443/"
SCOPES = "instagram_business_basic,instagram_business_content_publish"


class _Catcher(http.server.BaseHTTPRequestHandler):
    code = None

    def do_GET(self):
        q = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(q)
        _Catcher.code = params.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Done. You can close this tab and return to the terminal.")

    def log_message(self, *a):
        pass


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    app_id, app_secret = sys.argv[1], sys.argv[2]

    auth_url = (
        "https://www.instagram.com/oauth/authorize?"
        + urllib.parse.urlencode({
            "client_id": app_id,
            "redirect_uri": REDIRECT,
            "scope": SCOPES,
            "response_type": "code",
        })
    )
    print("If a browser doesn't open, visit:\n", auth_url)
    webbrowser.open(auth_url)

    # local HTTPS server (Instagram requires https redirect). Self-signed is fine;
    # click through the browser warning.
    httpd = http.server.HTTPServer(("localhost", 8443), _Catcher)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ctx.load_cert_chain(_self_signed())
    except Exception as exc:
        print("Could not create local TLS cert:", exc)
        sys.exit(1)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    while _Catcher.code is None:
        httpd.handle_request()
    code = _Catcher.code.rstrip("#_")

    # short-lived token
    r = requests.post("https://api.instagram.com/oauth/access_token", data={
        "client_id": app_id, "client_secret": app_secret,
        "grant_type": "authorization_code", "redirect_uri": REDIRECT, "code": code,
    }, timeout=30)
    r.raise_for_status()
    short = r.json()
    user_id, short_token = short["user_id"], short["access_token"]

    # exchange for long-lived (60 day) token
    r = requests.get("https://graph.instagram.com/access_token", params={
        "grant_type": "ig_exchange_token",
        "client_secret": app_secret,
        "access_token": short_token,
    }, timeout=30)
    r.raise_for_status()
    long_token = r.json()["access_token"]

    print("\nAdd these to .env and GitHub secrets:\n")
    print(f"IG_USER_ID={user_id}")
    print(f"IG_ACCESS_TOKEN={long_token}")


def _self_signed() -> str:
    """Generate a throwaway self-signed cert, return its file path."""
    import datetime
    import tempfile
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    f = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    f.write(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
    f.write(cert.public_bytes(serialization.Encoding.PEM))
    f.close()
    return f.name


if __name__ == "__main__":
    main()
