import os
import re
import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import google.generativeai as genai

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']

# --- Configuration ---
DOCUMENT_ID = 'YOUR_DOCUMENT_ID' # Replace with your Doc ID
OUTPUT_YAML_FILE = 'workload_parameters.yaml'

def get_google_docs_service():
    """Shows basic usage of the Docs API. Prints the title of a sample document."""
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('docs', 'v1', credentials=creds)
        return service
    except Exception as err:
        print(f"An error occurred during authentication: {err}")
        return None

def extract_text_from_doc(doc_content):
    """Recursively extracts text from Google Docs structural elements."""
    text = ""
    if 'body' in doc_content:
        for element in doc_content.get('body').get('content'):
            if 'paragraph' in element:
                for p_element in element.get('paragraph').get('elements'):
                    if 'textRun' in p_element:
                        text += p_element.get('textRun').get('content')
            elif 'table' in element:
                # Basic extraction for tables to ensure we don't lose data
                for row in element.get('table').get('tableRows'):
                    for cell in row.get('tableCells'):
                        text += extract_text_from_doc(cell)
    return text

def convert_text_to_yaml_via_llm(text):
    """Uses the Gemini API to parse unstructured document text into a YAML schema."""
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    
    # We use a model that is good at instruction following and extraction
    model = genai.GenerativeModel('gemini-1.5-pro')
    
    prompt = f"""
    You are a data extraction assistant. Read the following policy document about a university workload model.
    Extract all numerical parameters, formulas, baselines, and role percentages into a highly structured YAML format.
    
    Ensure the YAML is cleanly formatted, uses logical nesting (e.g., 'global_parameters', 'task_multipliers', 'roles_percentage'), and outputs percentages as decimals (e.g., 20% -> 0.20).
    Only output valid YAML. Do not include markdown formatting like ```yaml.
    
    Document Text:
    ---
    {text}
    ---
    """
    
    print("Sending text to Gemini API for processing...")
    response = model.generate_content(prompt)
    
    # Clean up the response to ensure it's pure YAML (removing potential markdown blocks)
    yaml_string = response.text.strip()
    if yaml_string.startswith("```yaml"):
        yaml_string = yaml_string.replace("```yaml", "", 1)
    if yaml_string.endswith("```"):
        yaml_string = yaml_string[::-1].replace("```", "", 1)[::-1]
        
    return yaml_string.strip()

def main():
    service = get_google_docs_service()
    if not service:
        return

    print(f"Fetching document ID: {DOCUMENT_ID}...")
    document = service.documents().get(documentId=DOCUMENT_ID).execute()
    
    print(f"Successfully loaded '{document.get('title')}'. Extracting text...")
    doc_text = extract_text_from_doc(document)
    
    if not doc_text.strip():
        print("No text found in the document.")
        return

    yaml_output = convert_text_to_yaml_via_llm(doc_text)
    
    # Verify the YAML is valid before saving
    try:
        yaml.safe_load(yaml_output)
        with open(OUTPUT_YAML_FILE, 'w') as f:
            f.write(yaml_output)
        print(f"\nSuccess! Extracted parameters have been saved to '{OUTPUT_YAML_FILE}'.")
    except yaml.YAMLError as exc:
        print("Error parsing the returned YAML from the LLM. The raw output was:")
        print(yaml_output)
        print(f"YAML Parse Error: {exc}")

if __name__ == '__main__':
    main()