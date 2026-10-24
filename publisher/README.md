# Rap Brain Manager — chaîne de signature (préparation)

Ce dossier contient des outils destinés **uniquement au Mac de publication**.
Aucune version installable n'est actuellement publiée.

- `publisher_key.swift init` crée une clé Ed25519 sous `~/Library/Application Support/RapBrainManager/publisher_ed25519.key` (mode 0600), ou réutilise la clé existante.
- `publisher_key.swift public` affiche uniquement la clé publique.
- `prepare_manifest.py` produit un catalogue signé **non installable** (`install_allowed: false`) pour des tests.
- Ne jamais transférer la clé privée, la coller dans ChatGPT ou la committer sur GitHub.

**Pas encore disponible :** la validation indépendante de cette signature dans le Manager installé, le contrôle de version du Manager, la sauvegarde/rollback du vrai paquet, et une mise à jour en un clic. Ces étapes doivent être validées avant toute installation réelle.

Le fichier `docs/channel-status.json` reste informatif et non signé ; il ne constitue jamais une autorisation d'installation.
