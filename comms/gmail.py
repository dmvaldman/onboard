import requests
import os
import imaplib
import email
import threading
import queue
import time
import json

from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv('creds/.env')


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

