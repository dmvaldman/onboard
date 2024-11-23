import requests
import os
import imaplib
import email
import threading
import queue
import time
import json

from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from comms.base import CommsBotBase
from utils.classes import File, ApplicationMessage

load_dotenv('creds/.env')

class GmailBot(CommsBotBase):
    def __init__(self):
        self._message_handler: MessageHandler = None
        self.email_queue = queue.Queue()

        # load json file
        with open('agents/agent.json') as f:
            agent_data = json.load(f)

        self.email_address = agent_data['email']
        self.email_admin_password = os.environ.get('GMAIL_APP_PASSWORD')
        self.name = agent_data['first_name'] + ' ' + agent_data['last_name']

        self.client = self.login()

    def login(self):
        try:
            # Connect to Gmail
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            result = mail.login(self.email_address, self.email_admin_password)

            if result[0] != "OK":
                print('Login failed. Exiting...')
                return

            return mail
        except Exception as e:
            print(f"Error logging into Gmail: {e}")
            return None

    def logout(self):
        try:
            self.client.logout()
        except Exception as e:
            print(f"Error logging out of Gmail: {e}")

    def get_unread_emails(self):
        try:
            self.client.select("inbox")

            # Search for unseen emails
            _, message_numbers = self.client.search(None, 'UNSEEN')

            for num in message_numbers[0].split():
                _, msg = self.client.fetch(num, "(RFC822)")
                email_body = msg[0][1]
                email_message = email.message_from_bytes(email_body)
                self.email_queue.put(email_message)
                print("New email received and queued!")

            self.client.close()
        except Exception as e:
            print(f"Error getting unread emails: {e}")

    def process_emails(self):
        while True:
            # Wait for new email
            email_message = self.email_queue.get()

            try:
                print(f"Processing email with subject: {email_message['subject']}")
                if email_message.is_multipart():
                    for part in email_message.walk():
                        if part.get_content_type() == "text/html":
                            body = part.get_payload(decode=True).decode()
                            break

                else:
                    body = email_message.get_payload(decode=True).decode()

                # Get email attachments
                files = []
                for part in email_message.walk():
                    if part.get_content_maintype() == 'multipart':
                        continue
                    if part.get('Content-Disposition') is None:
                        continue
                    filename = part.get_filename()
                    if filename:
                        files.append(File(
                            name=filename,
                            content=part.get_payload(decode=True)
                        ))

                sender_email = email.utils.parseaddr(email_message['from'])[1]
                subject = email_message.get('subject', None)
                date = email_message.get('date', None)
                cc_emails = email_message.get('cc', None)
                email_id = email_message.get('Message-ID', None)

                text = f"Please respond to this email from {sender_email}.\n\nSubject: {subject}\nDate: {date}\n\n{body}"

                message = ApplicationMessage(
                    user=sender_email,
                    text=text,
                    application="Gmail",
                    files=files
                )

                reply_body, files = self._message_handler.handle_message(message)

                # Send response email
                self.reply_to_email(email_id, subject, reply_body, attachments=files)
            except Exception as e:
                print(f"Error processing email: {e}")

    def reply_to_email(self, message_id, subject, reply_body, attachments=None):
        sender_email = email.utils.parseaddr(original_email['from'])[1]

        # Create a new email message
        reply = EmailMessage()
        reply['Subject'] = f"Re: {subject}"
        reply['From'] = formataddr((self.name, self.email_address))
        reply['To'] = sender_email
        reply['In-Reply-To'] = message_id
        reply['References'] = message_id
        reply.set_content(reply_body)

        # Attach files to the email
        if attachments:
            for file in attachments:
                reply.add_attachment(
                    file.content,
                    maintype='application',
                    subtype='octet-stream',
                    filename=file.name
                )

        # Send the email using self.client
        self.send_email(reply)

    def create_email(self, to, subject, body):
        email = EmailMessage()
        email['From'] = formataddr((self.name, self.email_address))
        email['To'] = to
        email['Subject'] = subject
        email.set_content(body)
        return email

    def send_email(self, email):
        try:
            self.client.send_message(email)
        except Exception as e:
            print(f"Error sending email: {e}")

    def create_and_send_email(self, to, subject, body):
        email = self.create_email(to, subject, body)
        self.send_email(email)

    def start(self):
        # Start email listener thread
        listener_thread = threading.Thread(target=self.get_unread_emails, daemon=True)
        listener_thread.start()

        # Start email processor thread
        processor_thread = threading.Thread(target=self.process_emails, daemon=True)
        processor_thread.start()

        # Keep the main thread alive
        while True:
            time.sleep(1)

if __name__ == "__main__":
    bot = GmailBot()
    bot.start()
