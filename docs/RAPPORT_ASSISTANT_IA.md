# Renatura · Assistant IA, modèles et données

Rapport du 11 novembre 2026.

L'assistant IA de Renatura peut maintenant interroger les 194 couches de l'Atlas régional, les prix des terrains, le bénéfice par euro et toutes les tendances climatiques, en plus des 4 modèles IA. Les modèles eux-mêmes n'ont pas changé : ils n'apprennent que sur l'occupation du sol, le bâti et les infrastructures. Les nouveaux outils ont été testés un par un sur les vraies données ; une conversation complète dans le chat reste à tester après redémarrage du serveur.

## 1. Corrections d'interface

| Page | Problème | Correction |
|---|---|---|
| Connaissances | Les boutons Voir / Désactiver / Supprimer débordaient de la table | Les boutons passent à la ligne dans leur cellule ; les titres longs se coupent ; la table défile dans sa carte en dernier recours |
| Toutes les pages | Pas de logo dans l'en-tête | Logo Renatura (feuille sur carré vert) à gauche de « renatura / NORMANDIE », 38 px (30 px sur mobile) |
| Atlas régional | Difficile de retrouver les couches choisies dans l'arbre | Couche active sur fond jaune vif ; son groupe et son thème ont un titre jaune pâle |
| Atlas régional | Pas de moyen d'effacer tous les choix | Bouton « ↺ Réinitialiser » : masque les couches, remet les réglages des groupes, vide recherche, commune et filtres, ferme le panneau, coupe l'analyse de maille, recentre la carte |

« Réinitialiser » ne rallume pas les couches par défaut : la carte reste vide. « Tout masquer » garde les filtres.

## 2. Les 4 modèles IA

Données d'apprentissage : 30 850 mailles de 1 km², CORINE Land Cover 1990 à 2018 et INSEE Filosofi 2015 et 2017. Chaque modèle est testé sur une période plus récente et sur des mailles jamais vues, contre une référence simple.

| Modèle | Question | Résultat (test) | Référence | Statut |
|---|---|---|---|---|
| TerritoryForecast | Quelles mailles vont s'artificialiser dans les 6 ans ? | AUC 0,896 | AUC 0,636 | Performant |
| EcoVulnerability | Quelles mailles risquent de perdre de l'habitat naturel ? | AUC 0,871 | AUC 0,502 | Performant |
| HumanPressure | Quelle population s'exerce sur la maille ? | R² 0,732 | R² 0,320 | Performant |
| SpeciesPhoto | Quelle espèce figure sur cette photo ? | 52,6 % en top-1 (validation) | — | Exploratoire |

Variables utilisées par les trois modèles territoriaux : parts CORINE (artificialisé, tissu urbain, zones industrielles et transports, chantiers, espaces verts urbains, agricole, forêts et milieux semi-naturels, zones humides, eau), artificialisation du voisinage (3 km) et de la période précédente, perte d'habitat de la période précédente. HumanPressure ajoute les routes OSM, les arrêts de transport, les ICPE, les voies ferrées et le bâti 2017.

Pour lire un risque : environ 1 % des mailles connaissent l'événement en 6 ans. Un risque de 8 % est donc faible en absolu, mais 8 fois supérieur à la moyenne. CORINE ne voit pas les changements de moins de 25 ha (haies, mares, petites extensions).

## 3. L'assistant IA et ses outils

L'assistant est un modèle de langage local qui ne calcule rien lui-même : il appelle des outils, et chaque chiffre de sa réponse vient d'un outil. Les appels sont visibles sous chaque réponse. Il connaît ses outils par leur description et par ses consignes ; le serveur en appelle aussi certains d'office quand la question contient des mots-clés.

| Outil | Ce qu'il fait | Mots qui le déclenchent d'office |
|---|---|---|
| `get_cell_profile`, `commune_summary` | Profil d'une maille ou d'une commune (V, D, P, O, RP, forêt) | un lieu nommé |
| `explain_index` | Formule, poids et couches d'un indice | — |
| `similar_cells` | Mailles au profil proche | — |
| `correlate` | Relation entre deux variables sur une zone | relation, lien, entre |
| `trend_projection` | Prolonge une tendance (climat, bâti) jusqu'à un horizon | tendance, futur, 2050 |
| `run_models`, `model_status` | Prédictions des 3 modèles territoriaux et leur précision | risque, modèle, prévision, artificialisation, population |
| analyse de photo | Modèle SpeciesPhoto + position GPS de la photo | photo jointe |
| `search_knowledge` | Base de connaissances (RAG) : espèces, milieux, méthode | espèce, habitat, comment, pourquoi… |
| **`atlas_layers`** (nouveau) | Liste des 194 couches de l'Atlas, filtrable | — |
| **`atlas_zone`** (nouveau) | Couches présentes autour d'un lieu (carrés de 5 × 5 km), par thème | éolien, méthaniseur, patrimoine, ZNIEFF, masse d'eau, carrière… |
| **`atlas_objects`** (nouveau) | Nom et distance des objets d'une couche près d'un lieu | — |
| **`price_benefit`** (nouveau) | Prix DVF 2021-2025 et bénéfice par euro, meilleures mailles | prix, coût, euro, bénéfice, achat, foncier |
| **`climate_summary`** (nouveau) | Toutes les tendances climatiques d'un lieu, écart 2016-2025, part bâtie | climat, météo |

Exemples vérifiés sur les données :

- Bayeux, ZNIEFF 1 à moins de 3 km : « La Grange du Grand Fumichon » à 2,5 km.
- Saint-Lô, méthaniseurs à moins de 15 km : 10, le plus proche au Mesnil-Rouxelin (0,9 km, en service depuis 2024).
- Lisieux, prix médian des terres agricoles : 9 156 €/ha (ventes 2021-2025).
- Coutances, climat : point de mesure à 6 km, température en hausse significative.

La page Assistant IA explique désormais, sous le chat, quels modèles et quelles données sont accessibles, avec 8 questions d'exemple cliquables.

## 4. Accès aux données : avant et après

| Donnée | Modèles IA | Assistant avant | Assistant maintenant |
|---|---|---|---|
| Prix médian des terrains (DVF 2021-2025) | Non | Non | Oui (`price_benefit`) |
| Bénéfice par euro (RP pour 10 000 €) | Non | Non | Oui (`price_benefit`) |
| Observations par euro | Non | Non | Non : indicateur calculé nulle part |
| Climat : température, jours chauds, gel, pluie, pluie d'été, sécheresse | Non | Un indicateur à la fois | Tous à la fois (`climate_summary`) |
| Tendance prolongée (2050…) | Non | Oui | Oui |
| NDVI (verdure d'été) | Non | Non | Lu si présent, mais la donnée est vide |
| Artificialisation | Oui | Oui | Oui |
| Biodiversité (ZNIEFF, Natura 2000, TVB, SRCE, Ramsar…) | Indirectement | Via le critère V | Oui, objet par objet |
| Eau (masses d'eau, cours d'eau, piézomètres, zones vulnérables…) | Surfaces en eau | Via V et D | Oui, objet par objet |
| Paysages et patrimoine | Non | Partiel (via O) | Oui (8 couches) |
| Énergie (éolien, PCAET, méthaniseurs, photovoltaïque, hydroélectricité, géothermie, chaufferies bois) | Non | Saturation éolienne seulement | Oui (17 couches) |
| Risques, carrières, mobilité, littoral, réglementation | Non | Partiel | Oui |
| Sols | Non | Non | Non : aucune donnée de sol dans le projet |

## 5. Limites et données manquantes

- **Climat incomplet.** La collecte ERA5 ne couvre que 8 points, tous dans l'ouest (Manche). Pour Caen, le point le plus proche est à 83 km. Au-delà de 40 km, l'assistant prévient que la tendance ne représente pas bien le lieu.
- **NDVI vide.** Le champ existe mais aucun point n'a de valeur.
- **Sols et observations par euro.** Ces données n'existent pas dans le projet.
- **Modèles non réentraînés.** La plupart des couches de l'Atlas ne sont qu'une photo de l'état actuel. Pour prédire un changement, il faut l'état avant ce changement ; avec une seule date, le modèle apprendrait sur des données qui contiennent déjà la réponse et ses scores seraient faux. Seul HumanPressure pourrait les utiliser sans ce risque.
- **Classement par risque.** `run_models` traite une maille ou une commune à la fois : impossible de demander « les 10 mailles les plus menacées du Calvados ». Le classement par bénéfice par euro, lui, fonctionne.
- **Précision du modèle photo.** Elle n'est consultable que sur la page Modèles IA, pas via l'assistant.
- **Lecture de l'Atlas.** Les comptes par carré de 5 km ne sont pas dédupliqués entre sources ; une couche absente n'est pas une preuve d'absence sur le terrain ; une couche partielle (PARTIAL) peut manquer des objets.

## 6. Prochaines étapes

- [ ] Redémarrer le serveur et tester une conversation complète avec les nouveaux outils.
- [ ] Relancer la collecte climat ERA5 et NDVI MODIS sur toute la Normandie.
- [ ] Ajouter un outil de classement des mailles par risque des modèles (`top_model_cells`).
- [ ] Brancher `species_model_status.json` dans `model_status`.
- [ ] Ajouter un outil qui explique une prédiction (variables qui pèsent le plus pour une maille).
- [ ] Réentraîner HumanPressure avec les couches de l'Atlas utiles (énergie, ICPE, transport), en gardant le test sur période récente.
- [ ] Définir « observations par euro » et choisir une source de données de sol.

## 7. Fichiers modifiés

| Fichier | Changement |
|---|---|
| `dist/connaissances.html`, `dist/connaissances.js` | Boutons de la table dans leur cellule |
| `dist/shared-header.js`, `dist/shared-header.css` | Logo dans l'en-tête |
| `dist/catalog-ui.js`, `dist/atlas.css` | Sélection en jaune (couche, groupe, thème) |
| `dist/atlas.html`, `dist/atlas.js` | Bouton Réinitialiser |
| `dist/assistant.html`, `dist/assistant.js` | Explication des modèles et des données sous le chat, questions cliquables |
| `pipeline/assistant/atlas_tools.py` (nouveau) | Outils `atlas_layers`, `atlas_zone`, `atlas_objects`, `price_benefit`, `climate_summary` |
| `pipeline/assistant/tools.py` | Enregistrement des nouveaux outils |
| `pipeline/assistant/chat.py` | Consignes de l'assistant et appels automatiques (prix, climat, Atlas) |
