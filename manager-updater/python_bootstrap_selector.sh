#!/bin/sh
# Finder uses Apple's restricted PATH; choose an installed Python that can
# import the updater before any backup, network request, or code replacement.
set -eu
if [ "$#" -lt 1 ]; then
  echo 'Installation refusée : entrée Python manquante.' >&2
  exit 2
fi
entry=$1
shift
for candidate in \
  /opt/homebrew/bin/python3 \
  /usr/local/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  /usr/bin/python3 "$(command -v python3 || true)"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ] && \
     "$candidate" -c 'import sys; raise SystemExit(not ((3, 10) <= sys.version_info[:2] < (4, 0)))' >/dev/null 2>&1; then
    exec "$candidate" -B "$entry" "$@"
  fi
done
echo 'Installation refusée : Python 3.10 ou plus récent introuvable sur ce Mac.' >&2
exit 2
