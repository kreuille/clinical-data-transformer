"""Cloud Function (Gen2) — Clinical Data Transformer backend.

Receives column names + 3 sample rows from the frontend,
sends them to Gemini to generate a standalone Python transformation script,
and returns that script to the browser.
"""

import json
import os
import re

import functions_framework
import google.generativeai as genai
from flask import jsonify, make_response

# -- Configuration --
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "https://kreuille.github.io"
).split(",")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))

# -- System Prompt --
SYSTEM_PROMPT = """\
Tu es un generateur expert de scripts Python pour la transformation de donnees cliniques.

# MISSION
Genere un script Python UNIQUE, COMPLET et AUTONOME qui transforme un fichier Excel
selon les instructions de l'utilisateur.

# CONTRAINTES STRICTES
1. Le script doit utiliser UNIQUEMENT les bibliotheques : pandas, openpyxl, tkinter.
2. Le script doit commencer par ouvrir un \`tkinter.filedialog.askopenfilename\`
   pour permettre a l'utilisateur de choisir son fichier Excel source.
3. Le script doit sauvegarder le resultat dans un nouveau fichier Excel
   (nom original suffixe \`_transformed.xlsx\`) via un \`tkinter.filedialog.asksaveasfilename\`.
4. Inclure une gestion d'erreurs robuste avec des messages clairs en francais.
5. Ajouter des commentaires en francais expliquant chaque etape.
6. NE PAS inclure de code d'installation de packages (pip install).
7. Le script doit fonctionner tel quel, sans modification, sur Windows, Mac et Linux.
8. Utilise \`if __name__ == "__main__":\` comme point d'entree.

# FORMAT DE REPONSE
Retourne UNIQUEMENT le code Python brut, sans balises markdown, sans explications,
sans \`\`\`python\`\`\`. Le premier caractere doit etre un # ou un import.
"""


# -- CORS helper --
def _cors_headers(origin: str | None) -> dict[str, str]:
    """Return CORS headers if the origin is allowed."""
    headers = {
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "3600",
    }
    if origin and any(origin.startswith(o.strip()) for o in ALLOWED_ORIGINS):
        headers["Access-Control-Allow-Origin"] = origin
    return headers


# -- Cloud Function entry point --
@functions_framework.http
def clinical_transform(request):
    """HTTP Cloud Function (Gen2) entry point."""

    origin = request.headers.get("Origin", "")
    cors = _cors_headers(origin)

    # Preflight
    if request.method == "OPTIONS":
        return ("", 204, cors)

    # Only POST allowed
    if request.method != "POST":
        return (jsonify(error="Method not allowed"), 405, cors)

    # -- Parse body --
    try:
        body = request.get_json(silent=True) or {}
        columns = body.get("columns")
        sample = body.get("sample")
        user_prompt = body.get("prompt", "").strip()

        if not columns or not sample or not user_prompt:
            return (
                jsonify(error="Champs requis manquants (columns, sample, prompt)."),
                400,
                cors,
            )
    except Exception:
        return (jsonify(error="JSON invalide."), 400, cors)

    # -- Build Gemini prompt --
    data_context = (
        f"Colonnes du fichier Excel : {json.dumps(columns, ensure_ascii=False)}\n\n"
        f"Echantillon (3 premieres lignes) :\n"
        f"{json.dumps(sample, ensure_ascii=False, indent=2)}\n"
    )

    user_message = (
        f"{data_context}\n"
        f"# INSTRUCTION DE TRANSFORMATION\n{user_prompt}"
    )

    # -- Call Gemini --
    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
        )
        response = model.generate_content(user_message)
        script = response.text.strip()

        # Strip markdown fences if Gemini wraps them anyway
        script = re.sub(r"^\`\`\`(?:python)?\n?", "", script)
        script = re.sub(r"\n?\`\`\`$", "", script)

    except Exception as exc:
        return (
            jsonify(error=f"Erreur Gemini : {exc}"),
            502,
            cors,
        )

    return (jsonify(script=script), 200, cors)
