"""Débrief — copilote post-appel pour les conseillers en assurance-vie.

L'appel se termine ; Débrief produit le compte rendu, prépare la mise à jour
HubSpot, contrôle le recueil DDA et les signaux LCB-FT, puis rédige la relance.
Le LLM comprend la conversation, le code décide : chaque champ doit être
sourcé dans l'appel et chaque règle de conformité est déterministe et testée.
"""

__version__ = "0.3.0"
