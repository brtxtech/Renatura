# Renatura — démarrage

1. Décompresser le ZIP.
2. Installer / démarrer Docker Desktop et disposer de Python 3.10 ou plus récent.
3. Dans ce dossier, lancer :

```sh
chmod +x run-renatura.command
./run-renatura.command
```

Le script prépare Python, démarre un vrai serveur Neo4j et importe les données liées à Caen. Le premier démarrage peut prendre plusieurs minutes. Ouvrir ensuite **http://localhost:8080/**.

- **Atlas régional** : catalogue Thème → Groupe → Couche, variantes de millésime, territoire et niveau ; filtre « Couches activées uniquement ».
- **Explorer** : pilote Pays d’Auge et scénarios historiques.
- **Neo4j** : requêtes Cypher réelles, résultats et relations. La requête initiale compte toutes les données importées de Caen par couche. Une autre commune peut être importée depuis la page.
- **Ajouter des données** : fichier GeoJSON / JSON / CSV, API GeoJSON ou WFS, métadonnées et aperçu réel. Une URL seule reste une référence.
- **Repères** sur les cartes : noms de communes toujours visibles, axes routiers, rail / tram et gares / arrêts facultatifs.

La version hébergée est statique : ses imports sont locaux au navigateur et elle n’héberge pas Neo4j. La version locale ci-dessus active la base réelle et la persistance des imports.

Les liens Neo4j `INTERSECTS_DISPLAY` reposent sur les géométries d’affichage simplifiées à 30 m : ce sont des liens d’exploration approximatifs, pas un diagnostic cadastral. Les sources partielles et les recouvrements entre années restent signalés.

Le ZIP contient l’interface, les couches préparées, les contours communaux, le catalogue, les scripts, les tests et la documentation. Les 1,75 Go d’originaux restent dans les archives livrées précédemment. Le serveur Neo4j est téléchargé par Docker au premier lancement ; une base préimportée n’est pas incluse dans le ZIP.

Pour consulter seulement la carte sans Docker :

```sh
python3 -m http.server 8080 --directory dist
```

Dans ce mode, les requêtes Neo4j sont désactivées. Voir **README_ATLAS.md** pour les détails, les limites et l’import régional complet.
