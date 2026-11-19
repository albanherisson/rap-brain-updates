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

## Pilote 009 : deux tests revus sur le Mac

Après les contrôles de source et de reprise des pilotes 005 à 008, l'action `reviewed_test_trial` vérifie le commit privé `a0b917cf04ee9f4de8852a1fc093c6691f51ca05`, son manifeste et les empreintes exactes du module et du fichier de test. Elle récupère les 23 sources dans un dossier temporaire, vérifie chaque empreinte et la syntaxe Python, puis exécute uniquement les deux tests `test_rhyme_validator.py`. Le dossier et la sortie brute sont supprimés avant la publication d'un résultat réduit aux empreintes et aux nombres. Le serveur installé et le Manager ne sont pas modifiés.

Le processus de test a une limite de temps et de ressources, mais le dossier temporaire et les variables d'environnement ne constituent pas un bac à sable du système macOS. Cette action n'est autorisée que pour ce code revu et épinglé ; elle n'accepte ni commande ni chemin libre dans la tâche GitHub. Le pilote attend une mise à niveau de l'agent avec `--upgrade-reviewed-test` avant l'activation de la file. L'installateur vérifie les empreintes de l'agent existant et restaure ses scripts précédents si le nouveau démarrage échoue.

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

### Résultat du pilote 009

Le Mac a publié `results/pilot-009.json` avec `status: pass` : 23 fichiers et 375 259 octets vérifiés, 16 fichiers Python analysés, deux tests revus réussis, copie temporaire supprimée et Ollama disponible. Le code candidat a été exécuté uniquement dans la copie temporaire pour ces deux tests. L'application installée et le Manager n'ont pas été modifiés.

## Pilote 010 : journal et retour arrière du Manager

L'action `manager_lab_trial` reprend le même commit privé et exige l'empreinte exacte du module `multi_file_trial.py` déjà présent dans les sources du Manager. Elle vérifie toutes les sources, copie les vrais `server.py` et `creative_engine.py` dans un laboratoire temporaire, et crée une base SQLite fictive. Le module du Manager y simule trois interruptions (`before_first`, `after_first`, `after_second`) et une activation réussie. Chaque interruption doit être reprise par un nouveau processus ; le code doit retrouver ses empreintes d'origine et les enregistrements fictifs ajoutés après l'interruption doivent rester présents. La copie et les sorties brutes sont supprimées ; seul un résultat agrégé est publié.

Il s'agit d'un essai du mécanisme d'activation sur des fichiers source copiés et une base fictive, pas d'un déploiement ou d'un test sur la base de l'utilisateur. La tâche ne fournit aucun chemin ni commande libre. La mise à niveau `--upgrade-manager-lab` contrôle les empreintes des quatre scripts installés, garde le plist et peut restaurer l'ancien agent si le redémarrage échoue.

### Résultat du pilote 010

La première tentative de mise à niveau du pont a été refusée et l'ancien agent restauré (empreinte `4a664f2b…652784c`, laboratoire absent). Après l'ajout d'un diagnostic d'étape à l'installateur, la mise à niveau a réussi. Le Mac a ensuite publié `results/pilot-010.json` avec `status: pass` : 23 fichiers privés vérifiés, trois reprises après interruption, une activation fictive réussie, base SQLite fictive préservée et copie temporaire supprimée. Aucun fichier de l'application ou de la base installées n'a été remplacé par ce pilote.

## Pilote 011 : inventaire du Manager en lecture seule

Le Manager signé et son relais de mise à jour disposent déjà de tests sur copies jetables (41 tests ciblés de mise à jour et 26 de réparation passés localement). Avant de les relier au pont, `manager_inventory` relève uniquement les empreintes de quatre ressources fixes dans les deux emplacements connus du Manager (`~/Applications` et le paquet Beta 14 dans `~/Downloads`) et indique si un dossier de sauvegarde existe. Il n'ouvre ni SQLite ni les contenus de l'utilisateur, ne suit pas de liens symboliques et ne modifie aucun fichier. La tâche `pilot-011` est préparée mais inactive jusqu'à la mise à niveau `--upgrade-manager-inventory` du pont ; la file reste sur `pilot-010`. Ce résultat servira à déterminer quel installateur signé correspond au Manager réellement présent, avant un essai d'installation sur copie complète.

### Résultat du pilote 011

Le Mac a publié `results/pilot-011.json` avec `status: pass`. Le paquet Beta 14 dans `~/Downloads` contient `launch_manager.py` (`dac886a0…b9b12ac`), `RapBrainManagerNative.swift` (`00192215…c1bad`) et `dashboard_beta14.html` (`9eb2df0a…b4e3a2`). Le bundle sous `~/Applications` existe, mais ne contient aucun de ces quatre noms de ressources. Un dossier de sauvegarde existe ; son contenu n'a pas été lu. La branche de réparation signée existante épingle une autre ligne de base (`e072f29f…722a6464` pour le lanceur, `d996f481…1e91b68` pour le Swift, `e7947990…0e56f27` pour le serveur), alors que le serveur actuellement relevé est `4cdab908…9b15ad8a7e16c`. Cet installateur ne peut donc pas être réutilisé tel quel. La copie source privée des 23 fichiers contient encore un autre agencement (`launcher.py` et `manager.py`) ; elle ne suffit pas à déduire quelle application est en cours d'exécution. Avant une installation réelle, prouver l'identité du Manager actif et produire un candidat signé ciblant les empreintes observées, puis répéter l'essai sur une copie complète.

## Pilote 012 : processus Manager, sans commandes publiées

La tâche `manager_process` utilise `/bin/ps -ww` et `lsof` en lecture seule sur le Mac. Elle ne publie ni PID ni ligne de commande : seulement quatre booléens indiquant si l'un des deux emplacements connus du Manager apparaît dans un processus, si le serveur de `~/Downloads/rap-brain` apparaît et si le port 8765 écoute. Ce recensement reste indicatif si le Manager est fermé ou si un autre processus mentionne son chemin. `pilot-012` est préparé mais inactif tant que `--upgrade-manager-process` n'a pas mis à niveau les deux scripts du pont ; la file reste sur `pilot-011`. Aucun installateur signé ni fichier de l'application ne sera exécuté par ce pilote.
