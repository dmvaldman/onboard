import requests
import os
import imaplib
import email
import threading
import queue
import time
import json

from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv('creds/.env')

def create_gsuite_user(email_address, first_name, last_name):
    # Set up credentials and create the service
    SCOPES = ['https://www.googleapis.com/auth/admin.directory.user']
    SERVICE_ACCOUNT_FILE = 'creds/onboard_service_account.json'

    credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)

    # Delegate domain-wide authority to the service account
    delegated_credentials = credentials.with_subject(os.environ.get('GSUITE_ADMIN_EMAIL'))

    service = build('admin', 'directory_v1', credentials=delegated_credentials)

    try:
        # Check if user exists
        try:
            existing_user = service.users().get(userKey=email_address).execute()
            print(f"User {email_address} already exists.")
            return existing_user
        except Exception as e:
            if "404" not in str(e):  # If error is not "user not found"
                raise e

        # User doesn't exist. Create them.
        password_temp = "password"
        user_data = {
            'primaryEmail': email_address,
            'name': {
                'givenName': first_name,
                'familyName': last_name
            },
            'password': password_temp,
            'changePasswordAtNextLogin': True
        }

        result = service.users().insert(body=user_data).execute()
        print(f"User {email_address} created successfully.")
        return result

    except Exception as e:
        print(f"An error occurred: {e}")
        return None

def listen_for_emails(email_address, email_password):
    while True:
        try:
            # Connect to Gmail
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            result = mail.login(email_address, email_password)

            if result[0] != "OK":
                print('Login failed. Exiting...')
                return

            mail.select("inbox")

            # Search for unseen emails
            _, message_numbers = mail.search(None, 'UNSEEN')

            # Search for all emails
            # _, message_numbers = mail.search(None, 'ALL')

            for num in message_numbers[0].split():
                _, msg = mail.fetch(num, "(RFC822)")
                email_body = msg[0][1]
                email_message = email.message_from_bytes(email_body)
                email_queue.put(email_message)
                print("New email received and queued!")

            mail.close()
            # mail.logout()
        except Exception as e:
            print(f"Error in email listener: {e}")

        print("Reconnecting to IMAP server...")
        time.sleep(10)  # Wait before reconnecting


def process_emails():
    while True:
        # Wait for new email
        email_message = email_queue.get()

        try:
            print(f"Processing email with subject: {email_message['subject']}")
            if email_message.is_multipart():
                for part in email_message.walk():
                    if part.get_content_type() == "text/html":
                        body = part.get_payload(decode=True).decode()
                        break
            else:
                body = email_message.get_payload(decode=True).decode()

            sender_email = email.utils.parseaddr(email_message['from'])[1]
            cc_emails = email_message['cc']

            # Parse the HTML email here...
            print(f"Email from: {sender_email}")
            print(f"CC: {cc_emails}")
            print(f"Email body: {body}")

        except Exception as e:
            print(f"Error processing email: {e}")

if __name__ == "__main__":
    # load agent.json
    with open('agents/agent.json', 'r') as f:
        agent_data = json.load(f)

    email_address = agent_data['email']
    first_name = agent_data['first_name']
    last_name = agent_data['last_name']
    gmail_app_password = os.getenv("EMAIL_APP_PASSWORD") # Created manually for now

    # Queue to hold new email events
    email_queue = queue.Queue()

    # Create workspace user and password
    # create_gsuite_user(email_address, first_name, last_name)

    # Long-poll for emails

    # Start email listener thread
    listener_thread = threading.Thread(target=listen_for_emails, args=(email_address, gmail_app_password), daemon=True)
    listener_thread.start()

    # Start email processor thread
    processor_thread = threading.Thread(target=process_emails, daemon=True)
    processor_thread.start()

    # Keep the main thread alive
    while True:
        time.sleep(1)

