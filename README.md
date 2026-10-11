# Capture d'écran

Outil léger de capture d'écran et d'annotation pour Ubuntu (session X11), inspiré de ksnip.
Un seul fichier Python, qui utilise GTK 3 (déjà présent dans Ubuntu) : rien à installer en plus.

## Installation

```sh
./install.sh
```

Copie `capture.py` dans `~/.local/bin/capture-ecran` et ajoute « Capture d'écran » à la liste des applications.
Relancez `./install.sh` après chaque modification du code.

## Utilisation

```sh
capture-ecran            # sélection d'une zone, directement
capture-ecran -f         # plein écran
capture-ecran -a         # fenêtre active
capture-ecran -d 3      # zone, après un délai de 3 s
capture-ecran -f -o x.png   # enregistre directement, sans éditeur
capture-ecran image.png  # ouvre une image dans l'éditeur
```

Une seule instance : relancer l'application ajoute un onglet à la fenêtre déjà ouverte.

## Éditeur

- Outils : Sélection, Flèche, Bulle, Crayon, Surligneur, Ligne, Rectangle, Rectangle plein,
  Ellipse, Texte, Numéro, Pixeliser, Flouter, Accolades `{` `}`.
- Tout élément peut être sélectionné, déplacé, redimensionné, recoloré, supprimé (Suppr).
- Annotation possible hors de la capture : l'image exportée s'agrandit (fond blanc).
- Onglets, rotation, ouverture d'images (bouton, glisser-déposer, « Ouvrir avec »).

## Raccourcis

| Raccourci | Action |
|---|---|
| Ctrl+N | Nouvelle capture |
| Ctrl+O | Ouvrir une image |
| Ctrl+S | Enregistrer |
| Ctrl+C | Copier l'image (et l'élément sélectionné) |
| Ctrl+V | Coller un clone de l'élément copié |
| Ctrl+D | Dupliquer l'élément sélectionné |
| Ctrl+Z / Ctrl+Y | Annuler / Rétablir |
| Ctrl+R / Ctrl+Maj+R | Pivoter à droite / à gauche |
| Ctrl+W | Fermer l'onglet |
| Ctrl+- / Ctrl++ | Dézoomer / Zoomer (aussi Ctrl + molette) |
| Ctrl+0 / Ctrl+9 | Zoom 100 % / Ajuster à la fenêtre |
| Suppr | Supprimer l'élément sélectionné |
| Échap | Désélectionner |
