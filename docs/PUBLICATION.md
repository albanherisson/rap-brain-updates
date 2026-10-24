# Publication sécurisée

**Statut : aucune mise à jour publiée.**

1. Héberger le site statique GitHub Pages à partir de `main` et `/docs`.
2. Préparer une version publiable sans données personnelles : aucune base SQLite, paroles, analyses, Lexicon, conversations, journaux, jetons ou clé privée.
3. Vérifier l'archive et produire un manifeste conforme au format effectivement accepté par le Manager.
4. Signer le manifeste avec une clé Ed25519 privée **stockée hors du dépôt**. Ne publier que le manifeste signé et les fichiers approuvés.
5. Dans le Manager, épingler la clé publique authentifiée. Utiliser une bibliothèque cryptographique reconnue : le vérificateur de laboratoire ne doit pas protéger les mises à jour réelles.
6. Tester une installation et un rollback sur une copie isolée avant d'activer une mise à jour réelle.

**À ce jour :** pas de manifeste `manifest.json`, pas de release 8.8.1, et pas d'auto-installation activée. L'existence du site ne prouve pas que le canal de production soit opérationnel.
