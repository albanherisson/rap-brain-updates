# P0 — Remote Development & Automation

## Décision et périmètre

Alban pilote les priorités et valide les changements ; ChatGPT conçoit et écrit le code ; Ollama est un auxiliaire local pour les tâches explicitement déléguées. Le pont Mac–GitHub doit permettre de préparer une tâche depuis Work, de la vérifier sur le Mac et de rapporter le résultat. Il ne doit pas exécuter du code arbitraire reçu depuis GitHub.

La P0 passe avant la suite du Decoding Engine. Le rangement des Téléchargements vient après la P0 et la reprise du Decoding Engine ; il ne conditionne pas le premier jalon distant.

## Étapes vérifiables

1. **Inventaire local** : exécuter `mac_preflight.py` sur le Mac et relever la version du serveur, la présence du Manager, de Git et d'Ollama. Lecture seule, sans parcourir la base ou les paroles.
2. **Canal de tâches** : choisir un espace GitHub approprié, avec contrôle des auteurs, identifiants de tâche uniques, état durable et opérations autorisées par une liste fermée. Le dépôt actuel `rap-brain-updates` est public et sert aux mises à jour signées : ne pas y envoyer de journaux, code privé ou données personnelles.
3. **Exécuteur local limité** : lecture d'une tâche approuvée, verrouillage contre les doublons, exécution sur copie isolée, tests, rapport expurgé et arrêt/retour arrière. Aucun accès direct en écriture à l'installation active.
4. **Premier aller-retour distant** : depuis Work, soumettre une tâche factice, la faire traiter sur le Mac, récupérer le résultat et vérifier l'identité et l'absence de double exécution.
5. **Fiabilisation** : reprise après redémarrage, expiration des tâches, erreurs réseau, contrôle des coûts et arrêt d'urgence ; seulement ensuite étendre aux tâches du Decoder, puis Professor, Lexicon et Creative Engine.

Le jalon distant est acquis à l'étape 4 ; la P0 entière à l'étape 5. Ne pas confondre publication GitHub, exécution sur Mac et installation dans le Manager.

## Diagnostic sur le Mac

Depuis le dossier du dépôt :

```bash
python3 remote-development/mac_preflight.py
```

Le script affiche un JSON limité à des indicateurs, versions et empreintes. Il ne lit pas les fichiers de données et ne contacte aucun service. Copier ce JSON dans la conversation pour préparer le canal suivant.

## Premier pilote distant

La tâche `pilot-001` sur cette branche demande seulement un contrôle de version et de présence des outils. `mac_bridge.py` lit la tâche sur l'API GitHub, refuse les champs ou actions inconnus, puis affiche un résultat sans base, paroles, chemins locaux, journaux ni jetons. Il ne lance aucune commande issue de la tâche.

```bash
python3 remote-development/mac_bridge.py pilot-001
```

La publication automatique du résultat est désactivée par défaut. L'option `--publish` demande un jeton GitHub à la saisie masquée pour écrire uniquement `remote-development/results/pilot-001.json` sur cette branche ; ce jeton doit avoir une portée limitée à ce dépôt avec la permission Contents en écriture. Le jeton n'est ni enregistré ni affiché. Ne jamais coller ce jeton dans le chat, le dépôt ou un journal. Cette première exécution est ponctuelle ; l'agent en arrière-plan et son authentification durable seront construits après validation de l'aller-retour.
