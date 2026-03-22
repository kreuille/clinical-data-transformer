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

SYSTEM_PROMPT = """You are a data transformation expert. You receive Excel column names, 3 sample data rows, and a user instruction describing the transformation they want.

RESPOND WITH ONLY A VALID JSON OBJECT. No markdown, no code fences, no explanation. Just the JSON.

The JSON has exactly 2 fields:

1. "js_code": The BODY of a JavaScript function (NOT the function declaration). This code receives a variable called "data" which is an array of objects where keys are column names. It must transform and return the result array.
   CRITICAL RULES:
   - Return ONLY the function body, NOT function(data){...}
   - Start directly with var result = ... and end with return result;
   - Use var (not let/const), function() (not =>)
   - Use string concat + (not template literals)
   - Handle null/undefined with checks like (row['col'] || '')
   - EXAMPLE: "var result = data.map(function(row) { var r = {}; for(var k in row) { if(row.hasOwnProperty(k)) r[k] = row[k]; } r['FullName'] = (row['First'] || '') + ' ' + (row['Last'] || ''); return r; }); return result;"

2. "python_script": A complete Python script that does the same transformation. Uses tkinter.filedialog for file selection, pandas for data manipulation, saves result as Excel.

IMPORTANT FOR MODIFICATIONS:
- If the conversation history contains previous code, the user wants to MODIFY that result
- Write NEW code that combines ALL previous transformations + the new one
- The new code must be standalone (not incremental) - it replaces the old code entirely

ALWAYS respond in the user language for the python_script comments."""


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
            'Colonnes du fichier Excel: ' + json.dumps(columns, ensure_ascii=False),
            'Echantillon de 3 lignes: ' + json.dumps(sample, ensure_ascii=False)
        ]
        if history:
            parts.append('=== HISTORIQUE DES TRANSFORMATIONS ===')
            for item in history:
                parts.append(item['role'].upper() + ': ' + item['content'])
            parts.append('=== FIN HISTORIQUE ===')
        parts.append('NOUVELLE INSTRUCTION DE L UTILISATEUR: ' + instruction)
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