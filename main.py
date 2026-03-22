import os
import re
import json
import functions_framework
from flask import jsonify, request
import google.generativeai as genai

GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', 'https://kreuille.github.io')

genai.configure(api_key=GOOGLE_API_KEY)

SYSTEM_PROMPT = """You are a data transformation expert. Given Excel column names, 3 sample rows, and a transformation instruction, respond with ONLY a valid JSON object (no markdown, no code fences).

The JSON must have exactly two fields:

1. "js_code": A JavaScript function body (ES5 ONLY). It receives a parameter named 'data' which is an array of objects (keys = column names). It must return the transformed array. STRICT RULES:
   - Use ONLY 'var', NEVER 'let' or 'const'
   - Use function() NEVER arrow functions =>
   - Use string concatenation with + NEVER template literals or backticks
   - Handle null/undefined values safely with checks
   - The function body must end with 'return result;'

2. "python_script": A complete standalone Python script using pandas and openpyxl that:
   - Imports tkinter and uses filedialog.askopenfilename() to let the user pick the input Excel file
   - Reads the Excel with pandas
   - Applies the SAME transformation as the js_code
   - Uses filedialog.asksaveasfilename() for the output path
   - Saves the result as a new Excel file

If there is conversation history, apply the NEW instruction on top of ALL previous transformations combined. Always return valid JSON only."""


def _cors():
    origin = request.headers.get('Origin', '')
    allowed = [o.strip() for o in ALLOWED_ORIGINS.split(',')]
    h = {
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Max-Age': '3600'
    }
    h['Access-Control-Allow-Origin'] = origin if origin in allowed else ''
    return h


@functions_framework.http
def clinical_transform(req):
    cors = _cors()
    if req.method == 'OPTIONS':
        return ('', 204, cors)
    try:
        data = req.get_json(silent=True)
        if not data:
            return (jsonify(error='JSON invalide.'), 400, cors)

        columns = data.get('columns')
        sample = data.get('sample')
        instruction = data.get('instruction', '')
        history = data.get('history', [])

        if not columns or not sample:
            return (jsonify(error='Champs requis manquants.'), 400, cors)

        parts = [
            'Colonnes: ' + json.dumps(columns, ensure_ascii=False),
            'Echantillon (3 lignes): ' + json.dumps(sample, ensure_ascii=False)
        ]
        if history:
            parts.append('Historique des transformations precedentes:')
            for item in history:
                parts.append(item['role'] + ': ' + item['content'])
        parts.append('Nouvelle instruction: ' + instruction)
        user_msg = '\n'.join(parts)

        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT
        )
        response = model.generate_content(user_msg)
        txt = response.text.strip()

        txt = re.sub(r'^```(?:json)?\n?', '', txt)
        txt = re.sub(r'\n?```$', '', txt)

        try:
            result = json.loads(txt)
        except json.JSONDecodeError:
            return (jsonify(error='Reponse IA invalide', raw=txt), 500, cors)

        return (jsonify(
            js_code=result.get('js_code', ''),
            python_script=result.get('python_script', '')
        ), 200, cors)

    except Exception as exc:
        return (jsonify(error=str(exc)), 500, cors)