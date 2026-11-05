# Renatura — Atlas régional de Normandie

L’atlas `dist/atlas.html` complète le pilote Pays d’Auge existant. Il exploite les fichiers et réponses API réellement reçus ; le catalogue conserve aussi les références sans données cartographiables. Le rapport chiffré livré fait foi : `dist/data/atlas/conversion-report.json`.

## Utilisation

Ouvrir le site, puis **Atlas régional**. Rechercher une commune, filtrer les couches par catégorie, origine ou complétude et cocher celles à afficher. Cliquer sur un objet pour lire ses attributs et sa provenance. **Analyser une maille** puis un clic sur la carte fournit les comptes d’intersections pour une maille de 5 × 5 km. Le diagnostic peut être exporté en GeoJSON.

Les couches de plus de 50 000 objets sont agrégées par maille à petite échelle ; à partir du zoom 13, les objets sont chargés par lots selon la vue. L’agrégat compte les objets qui intersectent la maille, pas uniquement leurs centres. Un même objet peut donc figurer dans plusieurs mailles. Le fond OpenStreetMap requiert Internet ; les données thématiques sont embarquées.

Dans **Sources & méthode**, consulter les 41 fichiers d’origine, le rapport de conversion, le catalogue de couches et les 1 016 références catégorisées. Les catégories et usages proviennent du catalogue de travail ; ils ne constituent pas une qualification réglementaire nouvelle.

## Lancer en local

Pour consulter la version statique, sans installation Python supplémentaire :

```sh
python3 -m http.server 8080 --directory dist
```

Ouvrir `http://localhost:8080/atlas.html`. Les diagnostics par maille sont déjà calculés. Ne pas ouvrir directement le HTML avec `file://`.

Pour le service facultatif d’analyse d’un polygone personnalisé :

```sh
chmod +x run-atlas.sh
RENATURA_SPATIAL_DB=/chemin/atlas_cache/normandie.sqlite ./run-atlas.sh
```

Ouvrir `http://localhost:8080/atlas.html`. Le bouton d’import de zone n’est activé que si l’index géométrique est disponible. Le serveur est local, lié à `127.0.0.1`. Le site hébergé utilise les mailles précalculées, sans serveur Python ni accès direct à Neo4j.

## Reconstruire depuis les archives déjà livrées

Les données brutes et les 41 originaux restent dans les archives de collecte précédemment fournies. Le présent projet ne duplique pas les 1,75 Go d’originaux. Décompresser les trois archives API et le paquet Neo4j dans un même dossier contenant `Neo4j_Renatura/`. Décompresser les cinq archives d’origine dans un dossier contenant `API_Audit/` et préparer les couches GPKG des archives 7z Nature en Ville avec le script d’extraction fourni dans les métadonnées du paquet initial.

Installer `requirements-atlas.txt` dans un environnement Python 3.11+ isolé, puis :

```sh
python3 pipeline/atlas/build_atlas.py \
  --source /chemin/Neo4j_Renatura \
  --files-root /chemin/API_Audit \
  --boundary /chemin/normandie.geojson \
  --cache /chemin/atlas_cache
python3 pipeline/atlas/build_context.py --database /chemin/atlas_cache/normandie.sqlite --workers 3
python3 pipeline/atlas/compress_display.py
```

Le fichier de contour doit avoir un `boundary_provenance.json` voisin ; les deux sont livrés dans `dist/data/atlas/` et peuvent être copiés dans un dossier de travail. Respecter cet ordre : compression en dernier. Les reçus du cache permettent de reprendre les conversions. Après une modification des sources, supprimer les reçus correspondants et les diagnostics `dist/data/atlas/zones/` avant recalcul ; ne pas réutiliser des diagnostics périmés.

L’index SQLite/RTree de travail est volumineux et reproductible ; il n’est pas embarqué dans les fichiers statiques. Il contient les géométries avant simplification d’affichage. `export_postgis.py` permet son import facultatif dans une instance PostGIS configurée par `DATABASE_URL` (installer `psycopg[binary]` séparément). Cet export n’a pas été exécuté sur une base distante.

## Méthode et limites

- Lecture des GeoJSON, Shapefile et GPKG via GDAL/Fiona ; lecture des réponses WFS GML avec prise en compte des axes et du CRS déclaré. Projection indéterminée ou géométrie non prise en charge : erreur consignée, sans coordonnées inventées.
- Reprojection en Lambert-93 (EPSG:2154), réparation des géométries invalides si nécessaire, intersection avec le contour normand Etalab généralisé à 5 m. Les limites et réparations peuvent modifier les géométries par rapport aux originaux.
- Calcul des intersections avec les géométries de travail, puis simplification à 30 m pour l’affichage uniquement, conversion en WGS84 et compression gzip sans perte supplémentaire.
- Les sources partielles, en erreur, sans géométrie et hors région restent référencées. Les objets nationaux hors Normandie ne sont pas affichés. La complétude API décrit la collecte d’origine, pas une garantie d’exhaustivité locale après conversion.
- Les variantes API/fichiers peuvent se recouvrir. Le total cartographique compte des enregistrements par couche, pas des objets uniques entre sources. Une absence de résultat ne démontre pas une absence d’enjeu.
- Aucun nouveau score de renaturation, aucune interdiction et aucune causalité ne sont déduits automatiquement. Le score expérimental du pilote reste propre à son périmètre historique.
- Les identifiants `_neo4j_id`, lorsqu’ils existent dans les extractions API, servent au rapprochement avec l’import du paquet Neo4j. L’atlas ne démarre pas une instance Neo4j et n’y importe pas les données automatiquement.
- Aucun secret ni clé API n’est nécessaire au navigateur pour lire les instantanés embarqués. Une actualisation nécessite une nouvelle collecte, une conversion et un déploiement.

## Provenance et licences

Les sources thématiques et licences déclarées sont dans les fiches et le catalogue. Contour régional et communes : Etalab, jeux `contours-administratifs/latest/geojson/regions-5m.geojson.gz` et `communes-100m.geojson.gz`, récupérés le 5 novembre 2026 ; Licence Ouverte 2.0. Les communes retenues appartiennent aux départements 14, 27, 50, 61, 76 ; leur point représentatif sert uniquement à centrer la carte. Fond : © OpenStreetMap contributors. Moteur Leaflet 1.9.4, licence BSD-2-Clause livrée dans `dist/vendor/leaflet/LICENSE`.

## Vérification

```sh
node --test tests/core.test.js tests/atlas-core.test.js
python3 -m unittest discover -s tests -p test_atlas.py
```

Les tests couvrent les calculs existants du pilote, les filtres, les trous des polygones, les axes GML et les intersections exactes du service local. Le rapport de conversion conserve les limites et erreurs par source.

## Catalogue structuré, Neo4j et nouveaux imports

La navigation contient **Atlas régional → Explorer → Neo4j → Ajouter des données**. Le catalogue public `dist/data/atlas/catalog-v2.json` utilise Thème → Groupe → Couche avec variantes. Il contient 10 thèmes, 26 groupes, 193 couches logiques et 234 variantes. `catalog-v2.csv` offre les champs demandés ; `catalog-review.json` trace les regroupements et exclusions. Les 354 références originales restent dans `catalog.json` et les 1 016 entrées dans `inventory.json`. Les sources alternatives et anciens formats apparaissent dans les fiches de provenance, pas comme couches distinctes.

Les variantes temporelles utilisent un sélecteur de millésime ; CORINE possède les modes Occupation / Changements. Les révisions préférées remplacent l’ancienne version dans le contrôle, sans supprimer sa référence. Les départements / territoires se sélectionnent dans le groupe ; « Tous » combine les sources départementales disponibles sans prétendre dédupliquer leurs objets. Les niveaux SRC et profondeurs géothermiques utilisent des boutons radio. La TVB dispose de noms d’affichage explicites, séparés des noms techniques conservés dans la provenance.

**Neo4j est un véritable service local, pas une imitation JavaScript.** Docker Desktop et Python 3.10+ sont requis. Depuis le dossier extrait :

```sh
chmod +x run-renatura.command
./run-renatura.command
```

Le script génère un mot de passe local dans `.env`, démarre Neo4j Community 5.26.32, importe réellement les métadonnées et les éléments liés à Caen, puis sert l’interface sur http://localhost:8080/. Le premier import peut prendre plusieurs minutes. La base persiste dans un volume Docker. Les secrets `.env`, la base de travail et les imports personnels ne sont pas inclus dans le ZIP.

Dans **Neo4j**, sélectionner une commune et utiliser **Importer / actualiser cette commune**, puis exécuter une requête Cypher. La requête agrégée initiale compte tous les enregistrements importés par couche pour Caen ; la vue de chemins est limitée à 100 chemins pour rester lisible. Le service plafonne l’affichage à 500 lignes (maximum configurable par requête : 1 000) et indique toute troncature. Les résultats peuvent être exportés. Les requêtes du navigateur sont strictement en lecture : plan EXPLAIN de type lecture, procédures / écritures / accès externes refusés, délai limité.

**La version web hébergée reste statique et n’héberge pas Neo4j.** Sa page Neo4j indique explicitement l’absence de connexion et fournit les requêtes / instructions. Les requêtes deviennent exécutables en ouvrant la version locale avec le service réel.

Le graphe utilise `Commune ← INTERSECTS_DISPLAY — Element → FROM_SOURCE → Source → VARIANT_OF → Layer → IN_GROUP → Group → IN_THEME → Theme`. Les liens `INTERSECTS_DISPLAY` sont calculés sur les géométries d’affichage simplifiées à 30 m et les contours communaux API Géo. Ils sont donc approximatifs et ne remplacent pas les intersections sur géométries de travail ni un contrôle cadastral. Les variantes de plusieurs années / sources peuvent décrire le même objet physique ; les comptes ne sont pas des objets uniques. Les sources partielles conservent leur statut.

Caen est importée par défaut. Les autres communes sont référencées mais leurs objets ne sont pas préimportés ; le bouton d’import les ajoute. Un import régional complet est possible, mais beaucoup plus volumineux :

```sh
NEO4J_URI=bolt://localhost:7687 NEO4J_PASSWORD=VOTRE_MOT_DE_PASSE \
python3 pipeline/graph/import_graph.py --all
```

**Ajouter des données** accepte GeoJSON, JSON géographique ou CSV avec champs latitude / longitude explicitement sélectionnés. Sans coordonnées, le CSV reste une table. Les URL seules restent des références ; un instantané API est marqué partiel si le total n’est pas connu ou si le plafond WFS de 10 000 objets est atteint. Le service local supporte aussi GML WFS avec projection déclarée et conserve les imports dans `user-data/datasets/`. En hébergement statique, IndexedDB les conserve seulement dans le navigateur ; le bouton d’export permet de les transférer. Les blocages CORS et les projections inconnues sont signalés, jamais corrigés en inventant des coordonnées. Les nouveaux imports apparaissent dans le catalogue après rechargement et sont intégrés à Neo4j lors de l’actualisation de la commune.

Les noms de communes restent visibles au-dessus des couches thématiques, y compris dans la carte 2D sans WebGL. Le menu **Repères** permet d’activer les axes routiers, les voies ferrées / tramways et les gares / arrêts. Ces repères OSM, simplifiés pour l’affichage, ne servent pas au calcul des scores et couvrent le rectangle régional avec les zones voisines. La provenance exacte est dans `dist/data/orientation/provenance.json`.

Les 1 016 entrées du catalogue et les 41 fichiers sont aussi importés comme nœuds `CatalogueEntry` et `File`, reliés aux sources par `DOCUMENTED_BY` et `REFERENCES_FILE`. Les 14 catégories historiques restent distinctes des 10 thèmes de navigation.
