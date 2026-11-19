"""Vox — an adaptive voice-controlled command system for macOS."""

import os
import ssl

__version__ = "0.0.1"

# python.org's macOS Python ships with NO CA certificates until its "Install Certificates.command" is
# run, so every urllib HTTPS call fails CERTIFICATE_VERIFY_FAILED: the Kokoro voice download (which
# then silently falls back to `say`), web search, Spotify and Composio. Point OpenSSL at certifi's
# bundle when the interpreter has none of its own. Set here so it applies before any SSL context exists.
if not os.environ.get("SSL_CERT_FILE"):
    _paths = ssl.get_default_verify_paths()
    if not (_paths.cafile and os.path.exists(_paths.cafile)) and not (
        _paths.capath and os.path.isdir(_paths.capath) and os.listdir(_paths.capath)
    ):
        try:
            import certifi  # already installed transitively (httpx, requests); guarded in case that changes

            os.environ["SSL_CERT_FILE"] = certifi.where()
        except ImportError:
            pass
