# Script to bulk delete assistants and files from OpenAI
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv('creds/.env', override=True)

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def delete_assistants():
    # List all assistants of certain names
    names = ["AI Analyst", "Employee"]
    while assistants := [assistant for assistant in client.beta.assistants.list(limit=100).data if assistant.name in names]:
        # delete all assistants with name "AI Analyst" in backwards order
        for assistant in reversed(assistants):
            try:
                client.beta.assistants.delete(assistant.id)
                print(f"Deleted assistant: {assistant.id}")
            except Exception as e:
                print(f"Failed to delete assistant: {str(e)}")

def delete_files():
    # List all files
    files = client.files.list(purpose='assistants').data
    files_output = client.files.list(purpose='assistants_output').data

    # delete all files
    for file in reversed(files + files_output):
        client.files.delete(file.id)
        print(f"Deleted file: {file.id}")

def delete_assistants_and_files():
    delete_assistants()
    delete_files()

if __name__ == "__main__":
    delete_assistants_and_files()