"""Prepare a copy-only Manager UI and parent bridge for the general updater.

The installed Beta 14 launcher/dashboard are never changed here. This output
must remain unpublished until the external helper, all imports, recovery,
and macOS signed-copy tests are included in one reviewed capability release.
"""
import hashlib

from beta14_one_click_candidate import once


LAUNCHER_SHA256 = '79130fbb4c0404c271c83242718945258e0f0dd8616cad61fb890228672dd2e4'
DASHBOARD_SHA256 = '43647e2449d4b7bfd6924502e728e8cf8bb5ebc0f7333d56d7e85bb0bbed1cb2'


PARENT_HANDLER = '''def handle_manager_update_request(root, rap_dir, backup_dir, state):
    req=root/'manager-update-request.json'
    if not req.exists():return False
    out=root/'manager-update-result.json'
    try:
        if req.is_symlink() or req.stat().st_size>1024:raise RuntimeError('invalid_manager_request')
        data=json.loads(req.read_bytes())
        req.unlink()
        if data!={'action':'install-signed-manager'}:raise RuntimeError('invalid_manager_request')
        secure_state=backup_dir/'secure-update'
        from manager_update_parent import prepare_handoff
        handoff=prepare_handoff(rap_dir,Path(__file__).resolve(),secure_state,
            state,secure_state/'helper'/'manager_update_helper.py')
        out.write_text(json.dumps({'state':'handoff','installation_performed':False}))
        handoff.release_for_parent_exit()
        return True
    except Exception as exc:
        out.write_text(json.dumps({'state':'refused','installation_performed':False,
            'reason':type(exc).__name__,'detail':str(exc)[:160]},ensure_ascii=False))
        return False

'''


def prepare_launcher(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != LAUNCHER_SHA256:
        raise ValueError('manager_launcher_baseline_changed')
    source = raw.decode('utf-8')
    get_anchor = "  if urlsplit(self.path).path=='/api/rapbrain/creative-install-state':\n"
    source = once(source, get_anchor,
        "  if urlsplit(self.path).path=='/api/rapbrain/manager-update-state':\n"
        "   f=root/'manager-update-result.json'\n"
        "   secure=backup_root/'secure-update'\n"
        "   try:\n"
        "    if (secure/'maintenance.ticket').exists():result={'state':'check_required','installation_performed':None}\n"
        "    elif f.is_file():result=json.loads(f.read_text())\n"
        "    elif (secure/'manager-handoff-result.json').is_file():\n"
        "     from pending_attempt_recovery import _private_json\n"
        "     result=_private_json(secure/'manager-handoff-result.json',4096)\n"
        "     if type(result) is not dict or result.get('state') not in ('committed','rolled_back','aborted','restored_stopped','check_required'):raise ValueError('invalid_manager_result')\n"
        "    else:result={'state':'idle','installation_performed':False}\n"
        "   except Exception:result={'state':'check_required','installation_performed':None}\n"
        "   return self.send(200,json.dumps(result).encode(),'application/json')\n"
        + get_anchor)
    post_anchor = "  if endpoint=='/api/rapbrain/creative-install':\n"
    source = once(source, post_anchor,
        "  if endpoint=='/api/rapbrain/manager-update':\n"
        "   if self.headers.get('X-RB-Manager-Token')!=signature_token or self.headers.get('Origin','') not in ('',f'http://127.0.0.1:{self.server.server_address[1]}'):\n"
        "    return self.send(403,b'{\"error\":\"unauthorized\"}','application/json')\n"
        "   req=root/'manager-update-request.json'\n"
        "   if req.exists():return self.send(409,b'{\"error\":\"already_pending\"}','application/json')\n"
        "   result=root/'manager-update-result.json'\n"
        "   if result.is_file():\n"
        "    try:previous=json.loads(result.read_text())\n"
        "    except (OSError,ValueError):return self.send(409,b'{\"error\":\"unknown_previous_state\"}','application/json')\n"
        "    if previous.get('state') in ('queued','handoff'):return self.send(409,b'{\"error\":\"already_running\"}','application/json')\n"
        "   result.write_text(json.dumps({'state':'queued','installation_performed':False}))\n"
        "   req.write_text(json.dumps({'action':'install-signed-manager'}))\n"
        "   return self.send(202,b'{\"state\":\"queued\"}','application/json')\n"
        + post_anchor)
    source = once(source, 'def main():\n', PARENT_HANDLER + 'def main():\n')
    loop_anchor = '                handle_creative_install_request(root,rap_dir,backup_dir,supervisor_state)\n'
    source = once(source, loop_anchor, loop_anchor +
        '                if handle_manager_update_request(root,rap_dir,backup_dir,supervisor_state):return 0\n')
    smoke_anchor = "            code,_=request(port,'/api/rapbrain/creative-install','POST')\n"
    source = once(source, smoke_anchor,
        "            code,_=request(port,'/api/rapbrain/manager-update','POST')\n"
        "            if code!=403:raise RuntimeError('Manager update without token accepted')\n"
        "            code,body=request(port,'/api/rapbrain/manager-update-state')\n"
        "            if code!=200 or json.loads(body).get('state')!='idle':raise RuntimeError('Manager update state invalid')\n"
        + smoke_anchor)
    output = source.encode('utf-8')
    compile(output, 'launch_manager.py', 'exec')
    return output


def prepare_dashboard(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != DASHBOARD_SHA256:
        raise ValueError('manager_dashboard_baseline_changed')
    source = raw.decode('utf-8')
    source = once(source,
        '<span>Vérifier le canal — installation désactivée</span>',
        '<span>Version signée et sauvegarde vérifiées avant installation</span>')
    source = once(source,
        'Les mises à jour réelles ne sont pas encore disponibles. Tu peux vérifier le canal public et la signature de la candidate de test.',
        'Le Manager vérifie la publication signée, sauvegarde Rap Brain et teste la restauration avant toute mise à jour. Il ferme son interface pendant l’installation.')
    source = once(source,
        '<button class="smallbutton" disabled title="Aucune publication Creative Engine signée">Installer une mise à jour réelle</button>',
        '<button class="smallbutton" onclick="installManagerUpdate()">Installer la mise à jour signée</button>')
    source = once(source, 'async function checkSigned(){',
        "async function installManagerUpdate(){if(!confirm('Installer une mise à jour signée du Manager et de Rap Brain ? Le Manager vérifiera la sauvegarde et la restauration avant de remplacer le code.'))return;write('updatelog','Vérification en cours…');try{let v=await post('/api/rapbrain/manager-update','X-RB-Manager-Token',SIGNATURE_TOKEN);write('updatelog',v);if(v.state==='queued')write('updatelog','Demande reçue. Le Manager peut se fermer pendant la mise à jour. Rouvre-le pour vérifier le résultat.')}catch(e){write('updatelog','Erreur : '+e.message)}}\n"
        'async function checkSigned(){')
    return source.encode('utf-8')
