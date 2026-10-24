# Sécurité du canal Rap Brain

**Aucune installation réelle autorisée à ce stade.**

- `channel-status.json` est un indicateur public **non signé**, uniquement informatif. Il ne doit jamais déclencher une installation.
- Un correctif ne devra être utilisable qu'après validation d'un manifeste Ed25519 signé, de la clé publique épinglée dans le Manager et de l'empreinte SHA-256 de l'archive.
- La clé **privée** sera générée et conservée sur le Mac de l'éditeur, hors de GitHub, jamais transmise dans la conversation.
- Ne jamais publier des paroles, analyses, bases SQLite, Lexicon, conversations, journaux personnels ou tokens.
- L'application macOS n'étant pas notarisée, Gatekeeper pourra encore afficher des avertissements.
- Avant toute installation : sauvegarde vérifiée, test sur copie, récupération après incident et contrôle d'activité.
