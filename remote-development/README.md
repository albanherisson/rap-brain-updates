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

`--watch` lit `queue/current.json` toutes les 60 secondes, ignore les tâches dont le résultat existe déjà, et publie les nouveaux résultats de la même manière. Il demande le jeton une fois à la saisie masquée et ne le conserve qu'en mémoire jusqu'à l'arrêt du processus (`Ctrl-C`). Il fonctionne tant que le Terminal reste ouvert et que le Mac dispose du réseau et ne dort pas. Ce pilote n'est pas encore un service au démarrage, ni une installation permanente.

## Veille durable P0 (utilisateur macOS)

Une fois le pilote ponctuel validé, ajouter le **même** jeton au trousseau de connexion via une invite masquée (ne jamais mettre le jeton dans la commande) :

```bash
security add-generic-password -a albanherisson -s com.gns.rapbrain.remote.p0 -l "Rap Brain Remote P0" -w
python3 remote-development/mac_bridge.py --check-keychain
```

Arrêter la veille ponctuelle avec `Ctrl-C` avant d'activer l'agent. Puis, depuis le dossier contenant les trois fichiers Python du pont :

```bash
python3 remote-development/mac_install_agent.py --install
```

L'installation refuse de remplacer des fichiers déjà différents. Elle copie uniquement `mac_bridge.py` et `mac_preflight.py` dans `~/Library/Application Support/RapBrainRemoteBridge`, crée un LaunchAgent dans `~/Library/LaunchAgents` et l'active dans la session utilisateur. Aucune donnée ou application Rap Brain n'est modifiée. Le plist ne contient aucun jeton. `launchd` relance la veille après une ouverture de session et si elle s'arrête ; une coupure réseau est simplement retentée toutes les 60 secondes. Le trousseau doit être déverrouillé. Pour arrêter la veille durable :

```bash
python3 remote-development/mac_install_agent.py --stop
```

Le pilote demeure limité à `health_check`. Il faut encore une politique d'exécution sur copies isolées et un canal privé avant de lui confier du code, des analyses ou des journaux.

### Ajustement du chemin d'Ollama

Le premier essai du LaunchAgent a traité `pilot-003` mais affiché `ollama_available: false`, alors que le Terminal interactif voyait Ollama. La mise à niveau capture le dossier de l'exécutable trouvé lors de l'installation et configure le `PATH` de l'agent ; elle vérifie aussi les emplacements habituels de l'application macOS. Pour mettre à niveau l'agent P0 déjà installé :

```bash
python3 remote-development/mac_install_agent.py --upgrade
```

L'opération vérifie les deux anciennes empreintes et le plist du pilote, arrête l'agent, remplace les deux scripts et le plist, puis le redémarre. En cas d'échec de démarrage, les anciens fichiers sont restaurés et l'ancien agent est relancé. Le résultat d'une nouvelle tâche doit confirmer `ollama_available: true` avant d'utiliser Ollama depuis la veille.

## Préparer le dépôt privé du code

Le pilote `pilot-004` a confirmé qu'Ollama est visible sous launchd. Avant de synchroniser le code complet, exécuter `mac_source_inventory.py` sur le Mac. Il inspecte uniquement les trois racines connues (application Rap Brain, Manager installé, sauvegardes du Manager), ignore les liens symboliques et ne lit pas le contenu des fichiers. Il écrit une liste locale des chemins candidats sous `~/Library/Application Support/RapBrainRemoteBridge/source_inventory.json` avec des droits restreints, sans écraser un rapport existant. La sortie Terminal ne contient que des nombres de fichiers et tailles par catégorie. Aucun transfert vers GitHub n'a lieu.

Même dans un dépôt privé, les fichiers `private_data`, bases, sauvegardes, journaux, clés et configurations nécessitent une sauvegarde séparée et ne sont pas des sources à pousser. La catégorie `source_candidate` n'est pas une approbation automatique : elle doit passer une revue des secrets avant toute synchronisation.

Le dépôt `rap-brain-source` a été créé en privé avec des exclusions initiales. L'inventaire réel a compté 23 sources candidates dans Rap Brain, 13 dans le Manager actif et 2 310 dans les sauvegardes. Les sauvegardes sont exclues de l'étape suivante. `mac_prepare_source_review.py` crée sur le Bureau une archive locale des seuls fichiers source des deux installations actives, après vérification du hash de `server.py`, des tailles, des liens et de motifs de secrets courants. Un soupçon de secret arrête la création. L'archive ne part pas automatiquement sur GitHub : elle doit être inspectée avant tout import. Le filtrage automatique ne garantit pas l'absence de secret.

### Revue du premier paquet

Le premier paquet produit avant correction contenait 31 fichiers, dont neuf instantanés sous `rap_brain/sauvegardes`. Aucun de ces neuf fichiers n'a été importé. Les 22 fichiers de l'installation active ont été vérifiés et placés sur une branche de revue du dépôt privé (`p0/import-active-source`, PR #1). Le script de préparation exclut désormais aussi le dossier français `sauvegardes`. L'agent de veille reste limité au contrôle de santé ; l'import de code ne déclenche aucune installation locale.

## Essai de lecture du code privé (sans installation)

`mac_private_source_trial.py` lit le manifeste du dépôt privé à l'empreinte `31236459f934145cc20b7274beeaf910c318cee0639325e7496021b0fa3233c7` et le commit `629b95df0cf28e21db941b82a823561d388eac67`. Il exige un jeton fine-grained distinct, limité au seul dépôt privé avec Contents **Read-only**, stocké dans le trousseau sous `com.gns.rapbrain.source.readonly.p0`. Il télécharge les 22 sources dans un dossier temporaire du pont, vérifie leurs tailles et SHA-256, analyse la syntaxe Python sans importer les modules, puis supprime le dossier. Le résultat ne contient ni code, ni données utilisateur, ni jeton. Il ne modifie pas l'application ou le Manager. La veille peut déclencher le même essai après sa mise à niveau contrôlée.

Après création du jeton en lecture seule, le saisir uniquement dans l'invite masquée du Terminal :

```bash
security add-generic-password -a albanherisson -s com.gns.rapbrain.source.readonly.p0 -l "Rap Brain Source Read Only P0" -w
python3 mac_private_source_trial.py --check-keychain
python3 mac_private_source_trial.py --run
```

La mise à niveau `--upgrade-private-trial` accepte uniquement les empreintes de l'agent déjà installé après le correctif Ollama, vérifie les deux jetons du trousseau et l'identité du plist, arrête la veille, installe le script de lecture privée et le pont étendu, puis relance l'agent. Si le redémarrage échoue, elle restaure l'ancien pont et le relance. La tâche `pilot-005` est préparée mais la file d'attente n'est pas activée avant cette mise à niveau. Cette action reste une lecture et un contrôle de syntaxe sur copie temporaire ; elle ne lance aucun test métier ni installation réelle.
