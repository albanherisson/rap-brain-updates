"""Small signed-channel update after the offline handoff repair.

The dashboard text reflects the now-working signed update action. This is
code-only; no library, database, model or configuration member is allowed.
"""
import hashlib
import io
import stat
import zipfile


BASELINE = 'b1b57c4036f658cad83fc7642a2476e3582f2f8bd73ae671ceb36d2f7020713f'
MEMBER = 'app/dashboard_beta14.html'
OLD = 'ⓘ Aucune installation automatique</strong><small>Une mise à jour exige un paquet signé.'
NEW = '✓ Mises à jour signées disponibles</strong><small>Le Manager sauvegarde et vérifie avant installation.'


def prepare_dashboard(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != BASELINE:
        raise ValueError('manager_update2_dashboard_baseline_changed')
    source = raw.decode('utf-8')
    if source.count(OLD) != 1:
        raise ValueError('manager_update2_dashboard_anchor_changed')
    return source.replace(OLD, NEW, 1).encode('utf-8')


def archive_for(dashboard):
    raw = prepare_dashboard(dashboard)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        item = zipfile.ZipInfo(MEMBER, (1980, 1, 1, 0, 0, 0))
        item.create_system = 3
        item.compress_type = zipfile.ZIP_DEFLATED
        item.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(item, raw)
    return stream.getvalue(), raw
