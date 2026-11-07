"""Give the Manager's primary update tile its advertised action.

The installed signed dashboard already owns the confirmation, channel check,
backup, handoff and result display in installManagerUpdate(). This narrow
change connects the prominent tile to that existing path.
"""
import hashlib


BASELINE = '681026db23d1573c40d05cfb7cab73eb8cce0cf60ee03ec8983a6f04ea8e461f'
OLD = '<button class="action purple" onclick="showDetails(\'updates\')">'
NEW = '<button class="action purple" onclick="installManagerUpdate()">'


def prepare_dashboard(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != BASELINE:
        raise ValueError('installed_dashboard_changed')
    text = raw.decode('utf-8')
    if text.count(OLD) != 1 or text.count('async function installManagerUpdate()') != 1:
        raise ValueError('update_action_changed')
    candidate = text.replace(OLD, NEW, 1).encode('utf-8')
    if candidate == raw:
        raise ValueError('update_action_missing')
    return candidate
