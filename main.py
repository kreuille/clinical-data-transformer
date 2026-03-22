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

SYSTEM_PROMPT = """You are an expert Python developer specialized in Excel data transformation using pandas and openpyxl.

You receive: Excel column names, 3 sample rows, and a user instruction.

RESPOND WITH ONLY A VALID JSON OBJECT. No markdown, no code fences, no explanation.

The JSON has exactly 2 fields:

1. "js_code": A SIMPLE JavaScript function body for DATA PREVIEW ONLY in a browser.
   - This is ONLY for showing transformed data in an HTML table (no formatting, no colors, no charts).
   - Return ONLY the function body (NOT function(data){...}).
   - Start with: var result = data.map(function(row){ ... }); return result;
   - Use var (not let/const), function() (not =>), string concat + (not backticks).
   - If the instruction is about formatting/colors/charts that cannot be shown in HTML, just return the data unchanged: "return data;"

2. "python_script": THIS IS THE MAIN OUTPUT. A complete, production-quality Python script.
   This script MUST:
   - Import tkinter, use filedialog.askopenfilename() for input file selection
   - Import pandas, openpyxl, and any needed library
   - Read the Excel file with pandas
   - Apply ALL transformations requested by the user including:
     * Data transformations (rename, merge, split, calculate, filter, sort...)
     * Visual formatting (cell colors, font styles, borders, column widths...)
     * Charts and graphs (using openpyxl.chart)
     * Conditional formatting
     * Number formats, date formats
   - Use filedialog.asksaveasfilename() for output path
   - Save as Excel with openpyxl engine
   - Include clear French comments explaining each step
   - Handle errors gracefully with try/except

IMPORTANT FOR ITERATIVE MODIFICATIONS:
- The conversation history contains previous code that was applied
- When user asks for modifications, write NEW COMPLETE code combining ALL previous transformations + the new request
- The new code must be standalone and self-contained

Respond in the user language for comments. ALWAYS return valid JSON only."""

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
            parts.append('=== HISTORIQUE DES TRANSFORMATIONS PRECEDENTES ===')
            for item in history:
                parts.append(item['role'].upper() + ': ' + item['content'])
            parts.append('=== FIN HISTORIQUE ===')
        parts.append('NOUVELLE INSTRUCTION: ' + instruction)
        user_msg = '\n'.join(parts)
        model = genai.GenerativeModel(model_name=GEMINI_MODEL, system_instruction=SYSTEM_PROMPT)
        response = model.generate_content(user_msg)
        txt = response.text.strip()
        txt = re.sub(r'^```(?:json)?\n?', '', txt)
        txt = re.sub(r'\n?```$', '', txt)
        try:
            result = json.loads(txt)
        except json.JSONDecodeError:
            return (jsonify(error='Reponse IA invalide', raw=txt), 500, cors)
        return (jsonify(
            js_code=result.get('js_code', 'return data;'),
            python_script=result.get('python_script', '')
        ), 200, cors)
    except Exception as exc:
        return (jsonify(error=str(exc)), 500, cors)