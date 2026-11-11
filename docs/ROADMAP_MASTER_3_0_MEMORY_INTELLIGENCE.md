# RAP BRAIN — Roadmap Master 3.0 : décision d'architecture (2026-11-11)

> Addendum à intégrer à la Roadmap Master 3.0 officielle. Ce fichier documente la décision sans renuméroter les 8 phases ni modifier le code ou les données.

## Ordre de priorité confirmé
1. **P0 — Remote Development & Automation** : clôture uniquement après validation de l'autonomie à distance de bout en bout.
2. **Decoding Engine** : finalisation des analyses ligne par ligne.
3. **Mémoire intelligente — NOUVELLE ÉTAPE, À FAIRE** : après validation du Decoding Engine et avant le Creative Engine.
4. **Creative Engine** : création originale appuyée sur cette mémoire, puis intégration de Professor, Lexicon, Vault selon les dépendances de la roadmap de référence.

## Préparer pendant le Decoding Engine, sans bifurcation
Définir un **contrat de sortie structurée** pour chaque analyse : morceau, ligne/segment, technique, sens multiples, concepts/thèmes, références, mécanisme de construction, contexte, relations entre notions, provenance et degré de confiance. La structure doit rester compatible avec un Knowledge Graph futur. Ne pas remplacer le décodage exhaustif, ni reconstruire le Manager, ni écraser les données existantes.

## Mémoire intelligente — périmètre
- **Knowledge Graph spécialisé rap** : liens explicites entre techniques d'écriture, ambiguïtés, significations, références culturelles et exemples décodés.
- **RAG hybride** : recherche lexicale et sémantique, avec reclassement et traçabilité des résultats.
- **Raisonnement en plusieurs étapes** : récupération ciblée, transfert des mécanismes, propositions originales, critique/contrôle et sélection.
- **Intégration** : réutiliser SQLite et l'infrastructure locale existante lorsque possible ; rester compatible avec MacBook Pro M3 32 Go et Ollama.
- **Protection** : sauvegardes, migrations non destructives, pas d'exposition publique des paroles ou données personnelles, jamais de modification silencieuse de la bibliothèque/SQLite/config.

## Validation et mesures de réussite
Sur le corpus initial d'un album de **19 morceaux**, comparer l'ancien RAG au système hybride avec le **même modèle et les mêmes prompts** :
- qualité et pertinence des techniques retrouvées ;
- justesse des liens entre analyses ;
- naturel de l'anglais, doubles sens, cohérence, originalité et musicalité des propositions ;
- nombre de propositions réellement utilisables et quantité de réécriture nécessaire ;
- mémoire, latence et stabilité sur le Mac.

**Critère de décision :** conserver les composants seulement si les tests démontrent un gain réel. Un Knowledge Graph ne garantit pas à lui seul un meilleur niveau artistique.

**Statut :** décision produit enregistrée ; conception détaillée et implémentation non commencées. Aucun changement de priorité de la P0 ni du Decoding Engine.
