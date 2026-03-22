"""Cloud Function (Gen2) — Clinical Data Transformer backend.

Two modes:
- preview: Gemini transforms sample rows and returns a preview (JSON)
- generate: Gemini generates a standalone Python script

Both modes support conversation history for iterative refinement.
"""

import json
import os
import re

import functions_framework
import google.generativeai as genai
from flask import jsonify

# -- Configuration --
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "https://kreuille.github.io"
).split(",")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))

# -- System Prompts --
SYSTEM_PROMPT_PREVIEW = """\\
Tu es un expert en transformation de donnees cliniques.

# MISSION
On te donne des colonnes et 3 lignes echantillons d'un fichier Excel,
ainsi qu'une serie d'instructions de transformation (historique).
Tu dois appliquer TOUTES les instructions cumulees sur les 3 lignes
et retourner le resultat.

# FORMAT DE REPONSE — JSON STRICT
Retourne UNIQUEMENT un objet JSON valide (sans balises markdown) avec :
{
  "new_columns": ["col1", "col2", ...],
  "transformed_sample": [
    {"col1": "val", "col2": "val"},
    ...
  ],
  "description": "Liste a puces des operations effectuees"
}

IMPORTANT :
- Pas de ```json```, pas de commentaires, juste le JSON brut.
- Le premier caractere doit etre {
- Les valeurs doivent etre des strings ou des nombres, pas null.
"""

SYSTEM_PROMPT_GENERATE = """\\
Tu es un generateur expert de scripts Python pour la transformation de donnees cliniques.

# MISSION
Genere un script Python UNIQUE, COMPLET et AUTONOME qui transforme un fichier Excel
selon TOUTES les instructions de l'utilisateur (fournies comme historique cumule).

# CONTRAINTES STRICTES
1. Le script doit utiliser UNIQUEMENT les bibliotheques : pandas, openpyxl, tkinter.
2. Le script doit commencer par ouvrir un `tkinter.filedialog.askopenfilename`
   pour permettre a l'utilisateur de choisir son fichier Excel source.
3. Le script doit sauvegarder le resultat dans un nouveau fichier Excel
   (nom original suffixe `_transformed.xlsx`) via un `tkinter.filedialog.asksaveasfilename`.
4. Inclure une gestion d'erreurs robuste avec des messages clairs en francais.
5. Ajouter des commentaires en francais expliquant chaque etape.
6. NE PAS inclure de code d'installation de packages (pip install).
7. Le script doit fonctionner tel quel, sans modification, sur Windows, Mac et Linux.
8. Utilise `if __name__ == "__main__":` comme point d'entree.

# FORMAT DE REPONSE
Retourne UNIQUEMENT le code Python brut, sans balises markdown, sans explications,
sans ```python```. Le premier caractere doit etre un # ou un import.
"""


# -- CORS helper --
def _cors_headers(origin):
    headers = {
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "3600",
    }
    if origin and any(origin.startswith(o.strip()) for o in ALLOWED_ORIGINS):
        headers["Access-Control-Allow-Origin"] = origin
    return headers


def _build_user_message(columns, sample, history):
    data_context = (
        f"Colonnes du fichier Excel : {json.dumps(columns, ensure_ascii=False)}\n\n"
        f"Echantillon (3 premieres lignes) :\n"
        f"{json.dumps(sample, ensure_ascii=False, indent=2)}\n"
    )
    instructions = "\n".join(
        f"- Instruction {i+1}: {h}" for i, h in enumerate(history)
    )
    return f"{data_context}\n# INSTRUCTIONS DE TRANSFORMATION (cumul)\n{instructions}"


# -- Cloud Function entry point --
@functions_framework.http
def clinical_transform(request):
    origin = request.headers.get("Origin", "")
    cors = _cors_headers(origin)

    if request.method == "OPTIONS":
        return ("", 204, cors)

    if request.method != "POST":
        return (jsonify(error="Method not allowed"), 405, cors)

    try:
        body = request.get_json(silent=True) or {}
        action = body.get("action", "generate")
        columns = body.get("columns")
        sample = body.get("sample")
        history = body.get("history", [])

        if not columns or not sample or not history:
            return (
                jsonify(error="Champs requis manquants (columns, sample, history)."),
                400, cors,
            )
    except Exception:
        return (jsonify(error="JSON invalide."), 400, cors)

    user_message = _build_user_message(columns, sample, history)

    if action == "preview":
        system_prompt = SYSTEM_PROMPT_PREVIEW
    else:
        system_prompt = SYSTEM_PROMPT_GENERATE

    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=system_prompt,
        )
        response = model.generate_content(user_message)
        result_text = response.text.strip()

        result_text = re.sub(r"^```(?:json|python)?\n?", "", result_text)
        result_text = re.sub(r"\n?```$", "", result_text)

    except Exception as exc:
        return (jsonify(error=f"Erreur Gemini : {exc}"), 502, cors)

    if action == "preview":
        try:
            preview_data = json.loads(result_text)
            return (jsonify(preview=preview_data), 200, cors)
        except json.JSONDecodeError:
            return (
                jsonify(error="Gemini n'a pas retourne un JSON valide.", raw=result_text),
                502, cors,
            )
    else:
        return (jsonify(script=result_text), 200, cors)
