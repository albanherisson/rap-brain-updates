# Démarrage distant de Rap Brain

Le pont dispose d’une action `manager_start`. Elle passe par le même point d’entrée local que le bouton Ouvrir Rap Brain du Manager. La réception d’un résultat `started` ou `already_running` confirme que le serveur attendu écoute et répond à `/api/health`.

Après une mise à jour signée, tout appel qui dépend du serveur peut demander ce démarrage dès que le Manager confirme l’installation. La demande publique `rapbrain-remote-task-v5` contient son identifiant, l’empreinte du serveur attendu, une expiration de moins de 24 heures et le commit de l’autorisation privée. Ce commit contient `remote-development/manager-start-authorizations/<id>.json`, de schéma `rapbrain-manager-start-v1`, avec le même identifiant, la même empreinte et la même expiration.

Les actions `manager_stop` et `manager_restart` utilisent `rapbrain-remote-task-v6`. L’autorisation privée `remote-development/manager-lifecycle-authorizations/<id>.json` de schéma `rapbrain-manager-lifecycle-v1` lie l’opération, la séquence installée, le commit de publication, les empreintes du manifeste et du serveur et l’expiration. Le pont vérifie le manifeste signé publié à ce commit et réutilise l’arrêt propre des mises à jour. Un décodage actif laisse l’opération en attente. Le redémarrage vérifie le Manager avant l’arrêt et garde un reçu local après l’arrêt pour reprendre le lancement sans arrêter une deuxième fois le serveur.

Le démarrage réutilise la preuve privée du dernier retour de mise à jour pour identifier le Manager sur la boucle locale.

L’action `manager_reopen` utilise la même autorisation de cycle. Elle vérifie une fenêtre native du Manager, attend un serveur libre, arrête Rap Brain proprement, quitte l’application Manager puis rouvre sa fenêtre et relance Rap Brain. Le résultat expose séparément `manager_close_observed`, `manager_reopened` et `manager_window_present`. Le contrôle natif ne lit pas les titres ou contenus des fenêtres.

Le lancement natif utilise `NSWorkspace.openApplication` avec la substitution désactivée. L’application du chemin revu sert de référence signée. Si macOS renvoie une copie exécutée à une autre adresse, le contrôle exige le même identifiant de bundle et le même `kSecCodeInfoUnique`, après validation stricte du bundle et validation de la signature du processus par `SecCodeCopyGuestWithAttributes`. Le nom seul ne permet jamais de contrôler une application. Le cycle quitte au plus huit instances reconnues de cette version exacte, puis attend leur disparition avant la réouverture. Les erreurs de lancement macOS restent identifiables par leur code numérique, sans publier de chemin ou de journal privé. Si une opération native échoue après l’arrêt du serveur, le pont tente de relancer le serveur et rapporte l’échec du cycle avec `server_recovered`, sans déclarer le cycle réussi.

L’activation unique utilise `mac_activate_manager_start.py` avec les fichiers `mac_manager_install_request.py`, `mac_manager_start_request.py` et `../mac_install_agent.py` placés dans le même dossier. L’installateur existant vérifie la version installée, relance l’agent et restaure ses fichiers si la relance échoue. Les demandes d’installation signée continuent d’utiliser le même Manager.

`mac_activate_manager_lifecycle.py` met à niveau les deux versions précédentes du démarrage distant et inclut le contrôle corrigé du Manager. Il réutilise la même installation locale de l’agent.

Tests locaux depuis la racine du dépôt :

```sh
python3 -m unittest discover -s manager-updater -p 'test_remote_manager*.py'
```
