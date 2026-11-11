"""Fetch the first guarded bootstrap from one pinned GitHub Pages channel.

Authenticate the publisher and active code baseline before downloading the
archive. Redirects, foreign hosts, oversize responses and unsigned packages
are refused. This does not install or launch any code.
"""
import urllib.request

from bootstrap_full_release import (CHANNEL, allowed_archive_url,
                                    verify_full_bootstrap, verify_full_manifest)
from bootstrap_release import PUBLISHER_PIN
from creative_release import Refused


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refused('bootstrap_redirect_refused')


def fetch(url, cap):
    if url != CHANNEL:
        allowed_archive_url(url)
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(url, headers={'Accept-Encoding': 'identity'}),
                     timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise Refused('bootstrap_response_changed')
        raw = response.read(cap + 1)
    if not 0 < len(raw) <= cap:
        raise Refused('bootstrap_download_size')
    return raw


def download_bootstrap(original_server, original_launcher, original_dashboard,
                       *, pinned_key=PUBLISHER_PIN, fetcher=fetch):
    raw = fetcher(CHANNEL, 65536)
    manifest = verify_full_manifest(raw, original_server, original_launcher,
                                    original_dashboard, pinned_key=pinned_key)
    archive = fetcher(manifest['archive_url'], manifest['archive_bytes'])
    verify_full_bootstrap(raw, archive, original_server, original_launcher,
                          original_dashboard, pinned_key=pinned_key)
    return raw, archive, manifest
