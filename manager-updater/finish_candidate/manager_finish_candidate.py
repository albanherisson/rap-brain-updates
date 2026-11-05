"""Candidate for one substantive signed Manager update after repair 3.

Builds only launcher and dashboard bytes from exact installed baselines. The
launcher checks a signed channel sequence before requesting a disruptive
handoff; the existing transaction still performs all backups and rollback.
"""
import hashlib


LAUNCHER = '03b3079b7ebcbfec090eb30367357eb6354703273a510b71c7fef702c0536d31'
DASHBOARD = 'd4c8c322c038125c19b19e3722ffd5a97e7974844cf31322a85660ab2a3e6b8b'
OLD_PARENT = '''        from manager_update_parent import prepare_handoff
        stable_launcher='''
NEW_PARENT = '''        from manager_update_parent import prepare_handoff
        from manager_update_release import CHANNEL, fetch, verify_manifest
        from pending_attempt_recovery import _private_json
        receipt=secure_state/'manager-accepted.json'
        accepted=0
        if receipt.exists():
            saved=_private_json(receipt,256)
            if (type(saved) is not dict or saved.keys()!={'sequence'} or
                    type(saved['sequence']) is not int or saved['sequence']<0):
                raise RuntimeError('manager_accepted_record_invalid')
            accepted=saved['sequence']
        signed=fetch(CHANNEL,65536)
        latest=verify_manifest(signed)
        if latest['sequence']<=accepted:
            out.write_text(json.dumps({'state':'up_to_date',
                'installation_performed':False,'sequence':accepted}))
            return False
        stable_launcher='''
OLD_SECTION = '<section class="panel section details" id="updates">'
NEW_SECTION = '<section class="panel section" id="updates">'
OLD_BUTTON = '<button class="smallbutton" onclick="checkGithub()">Vérifier GitHub</button>'
NEW_BUTTON = '<button class="smallbutton" onclick="checkGithub()">Ouvrir le contrôle GitHub</button>'
OLD_JS = "write('updatelog','Clique « Vérifier mon canal GitHub » dans la page ouverte.')"
NEW_JS = "write('updatelog','Dans la page ouverte, clique « Vérifier mon canal GitHub ». Aucun fichier ne sera installé.')"
OLD_RESPONSE = "if(v.state==='queued')write('updatelog','Demande reçue. Le Manager peut se fermer pendant la mise à jour. Rouvre-le pour vérifier le résultat.')"
NEW_RESPONSE = ("if(v.state==='queued'){for(let i=0;i<40;i++){"
                "await new Promise(r=>setTimeout(r,500));try{let state=await get('/api/rapbrain/manager-update-state');"
                "if(state.state==='queued')continue;"
                "if(state.state==='up_to_date')write('updatelog','Le Manager est déjà à jour. Aucune installation effectuée.');"
                "else if(state.state==='refused')write('updatelog',state);"
                "else write('updatelog','Le Manager se ferme pendant la mise à jour. Rouvre-le pour vérifier le résultat.');"
                "return}catch(e){break}}write('updatelog','Vérification en cours. Rouvre le Manager pour vérifier le résultat.')}")


def _replace(raw, baseline, changes, name):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != baseline:
        raise ValueError(name + '_baseline_changed')
    source = raw.decode('utf-8')
    for old, new in changes:
        if source.count(old) != 1:
            raise ValueError(name + '_anchor_changed')
        source = source.replace(old, new, 1)
    candidate = source.encode('utf-8')
    if name.endswith('.py'):
        compile(candidate, name, 'exec')
    return candidate


def prepare_launcher(raw):
    return _replace(raw, LAUNCHER, [(OLD_PARENT, NEW_PARENT)], 'launch_manager.py')


def prepare_dashboard(raw):
    return _replace(raw, DASHBOARD, [(OLD_SECTION, NEW_SECTION),
        (OLD_BUTTON, NEW_BUTTON), (OLD_JS, NEW_JS),
        (OLD_RESPONSE, NEW_RESPONSE)], 'dashboard_beta14.html')
