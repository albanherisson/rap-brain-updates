"""Prepare a Beta 14 UI request bridge on a separate, pinned app copy.

The HTTP child only records an authenticated request inside its disposable
root. The parent, which owns the server Popen handle, invokes the signed
Creative transaction. Nothing here edits an installed app. The candidate must
not ship until its runtime resources are included in a signed bootstrap.
"""
import hashlib

from recovery_start_guards import prepare_launcher as guarded_launcher


EXPECTED_DASHBOARD = 'aa03ec8e0c11f117d26782276c13e31d79c44a7f70731f3728590acebb1d8d36'


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unsupported_beta14_install_anchor')
    return source.replace(old, new, 1)


PARENT_HANDLER = '''def handle_creative_install_request(root, rap_dir, backup_dir, state):
    req=root/'creative-install-request.json'
    if not req.exists():return
    out=root/'creative-install-result.json'
    try:
        if req.is_symlink() or req.stat().st_size>1024:raise RuntimeError('invalid_install_request')
        data=json.loads(req.read_bytes())
        req.unlink()
        if data!={'action':'install-signed-creative'}:raise RuntimeError('invalid_install_request')
        out.write_text(json.dumps({'state':'running','installation_performed':False}))
        from creative_install_controller import install_owned_creative
        result=install_owned_creative(rap_dir,backup_dir/'secure-update',state)
        if type(result) is not dict or result.get('state') not in ('committed','rolled_back','aborted','restored_stopped'):
            raise RuntimeError('unexpected_install_result')
        result=dict(result)
        result['outcome']=result['state']
        result['state']='finished' if result['outcome']=='committed' else 'refused'
        out.write_text(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        out.write_text(json.dumps({'state':'refused','installation_performed':False,
            'reason':type(exc).__name__,'detail':str(exc)[:160]},ensure_ascii=False))

'''


def prepare_launcher(raw):
    source = guarded_launcher(raw).decode('utf-8')
    get_anchor = "  if urlsplit(self.path).path=='/api/rapbrain/creative-signed-state':\n"
    get_route = ("  if urlsplit(self.path).path=='/api/rapbrain/creative-install-state':\n"
        "   f=root/'creative-install-result.json'\n"
        "   try:output=json.loads(f.read_text()) if f.is_file() else {'state':'idle','installation_performed':False}\n"
        "   except (OSError,ValueError):output={'state':'refused','installation_performed':False}\n"
        "   return self.send(200,json.dumps(output).encode(),'application/json')\n")
    source = once(source, get_anchor, get_route + get_anchor)
    post_anchor = "  if endpoint=='/api/rapbrain/creative-signed-check':\n"
    post_route = ("  if endpoint=='/api/rapbrain/creative-install':\n"
        "   if self.headers.get('X-RB-Creative-Token')!=signature_token or self.headers.get('Origin','') not in ('',f'http://127.0.0.1:{self.server.server_address[1]}'):\n"
        "    return self.send(403,b'{\"error\":\"unauthorized\"}','application/json')\n"
        "   req=root/'creative-install-request.json'\n"
        "   if req.exists():return self.send(409,b'{\"error\":\"already_pending\"}','application/json')\n"
        "   result=root/'creative-install-result.json'\n"
        "   if result.is_file():\n"
        "    try:previous=json.loads(result.read_text())\n"
        "    except (OSError,ValueError):return self.send(409,b'{\"error\":\"unknown_previous_state\"}','application/json')\n"
        "    if previous.get('state') in ('queued','running'):return self.send(409,b'{\"error\":\"already_running\"}','application/json')\n"
        "   result.write_text(json.dumps({'state':'queued','installation_performed':False}))\n"
        "   req.write_text(json.dumps({'action':'install-signed-creative'}))\n"
        "   return self.send(202,b'{\"state\":\"queued\"}','application/json')\n")
    source = once(source, post_anchor, post_route + post_anchor)
    source = once(source, 'def main():\n', PARENT_HANDLER + 'def main():\n')
    loop_anchor = "                handle_creative_signed_request(root,Path(__file__).with_name('verify_creative_signed_p10.py'))\n"
    source = once(source, loop_anchor, loop_anchor +
        '                handle_creative_install_request(root,rap_dir,backup_dir,supervisor_state)\n')
    smoke_anchor = "            code,_=request(port,'/api/rapbrain/backup','POST')\n"
    source = once(source, smoke_anchor,
        "            code,_=request(port,'/api/rapbrain/creative-install','POST')\n"
        "            if code!=403:raise RuntimeError('Creative install without token accepted')\n"
        "            code,state_body=request(port,'/api/rapbrain/creative-install-state')\n"
        "            if code!=200 or json.loads(state_body).get('state')!='idle':raise RuntimeError('Creative install state invalid')\n"
        + smoke_anchor)
    result = source.encode('utf-8')
    compile(result, 'launch_manager.py', 'exec')
    return result


def prepare_dashboard(raw):
    if hashlib.sha256(raw).hexdigest() != EXPECTED_DASHBOARD:
        raise ValueError('unexpected_beta14_dashboard')
    source = raw.decode('utf-8')
    source = once(source,
        '<button class="smallbutton" disabled title="Installation réelle non disponible : validation serveur requise">Installer le Creative Engine</button>',
        '<button class="smallbutton" onclick="installCreative()">Installer le Creative Engine signé</button>')
    source = once(source,
        "Vérifie la signature Ed25519 du paquet P8, son intégrité et son remplacement/restauration sur une copie temporaire. Aucune installation réelle n'est autorisée.",
        "Le test P8 reste limité aux copies. Le bouton d'installation accepte uniquement une nouvelle publication de production signée ; le Manager vérifie la sauvegarde et peut refuser si le serveur est occupé.")
    source = once(source, 'Installation désactivée</span>', 'Publication signée requise</span>')
    source = once(source, 'async function engineTrial(){',
        "async function installCreative(){if(!confirm('Installer le Creative Engine signé ? Le Manager vérifiera la signature et les sauvegardes avant toute modification.'))return;write('creativeSignedLog','Installation en cours…');try{let v=await post('/api/rapbrain/creative-install','X-RB-Creative-Token',SIGNATURE_TOKEN);write('creativeSignedLog',v);if(v.state==='queued')await waitResult('/api/rapbrain/creative-install-state','creativeSignedLog')}catch(e){write('creativeSignedLog','Erreur : '+e.message)}}\n"
        'async function engineTrial(){')
    return source.encode('utf-8')
