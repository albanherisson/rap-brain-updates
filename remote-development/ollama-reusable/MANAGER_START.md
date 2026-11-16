# Démarrage distant de Rap Brain

Le pont dispose d’une action `manager_start`. Elle passe par le même point d’entrée local que le bouton Ouvrir Rap Brain du Manager. La réception d’un résultat `started` ou `already_running` confirme que le serveur attendu écoute et répond à `/api/health`.

Après une mise à jour signée, tout appel qui dépend du serveur peut demander ce démarrage dès que le Manager confirme l’installation. La demande publique `rapbrain-remote-task-v5` contient son identifiant, l’empreinte du serveur attendu, une expiration de moins de 24 heures et le commit de l’autorisation privée. Ce commit contient `remote-development/manager-start-authorizations/<id>.json`, de schéma `rapbrain-manager-start-v1`, avec le même identifiant, la même empreinte et la même expiration.

L’activation unique utilise `mac_activate_manager_start.py` avec les fichiers `mac_bridge.py`, `mac_manager_start_request.py` et `../mac_install_agent.py` placés dans le même dossier. L’installateur existant vérifie la version installée, relance l’agent et restaure ses fichiers si la relance échoue. Les demandes d’installation signée continuent d’utiliser le même Manager.

Tests locaux depuis la racine du dépôt :

```sh
PYTHONPATH=remote-development/signed-restart:remote-development:remote-development/ollama-reusable \
  python3 -m unittest discover -s remote-development/ollama-reusable -p test_mac_manager_start_request.py
```
