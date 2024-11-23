import os
import requests
import time

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
from agents.agent import MessageHandler
from typing import List, Dict
from utils.classes import File, ApplicationMessage
from comms.base import CommsBotBase

class SlackBot(CommsBotBase):
    def __init__(self):
        load_dotenv('creds/.env')

        self.app = App(
            token=os.getenv("SLACK_BOT_TOKEN"),
            signing_secret=os.getenv("SLACK_SIGNING_SECRET")
        )

        self.workspace_info = {}

        # Register event handlers
        self._register_handlers()

        self._message_handler: MessageHandler = None

    def _register_handlers(self):
        """Register all event handlers with Slack Bolt"""
        self.app.event("message")(self.handle_message)
        self.app.event("app_mention")(self.handle_mention)
        self.app.event("app_home_opened")(self.handle_app_home_opened)
        self.app.event("member_joined_channel")(self.handle_channel_join)
        self.app.command("/bothelp")(self.handle_help_command)

    def handle_message(self, event, say, client):
        """Route messages to appropriate handlers"""
        # Skip bot messages
        if event.get("bot_id"):
            return

        channel_type = event.get("channel_type")

        if channel_type == "im":
            self._handle_dm(event, say, client)
        elif channel_type in ["channel", "group", "mpim"]:
            self._handle_channel_message(event, say, client)

    def _process_files(self, event, client) -> List[File]:
        """Process files attached to a message"""
        files = []
        if not event.get("files"):
            return files

        file_data = event["files"]
        for file in file_data:
            # Get file info
            file_info = client.files_info(file=file["id"])

            # Download the file content using the private URL
            response = requests.get(
                file["url_private"],
                headers={"Authorization": f"Bearer {os.getenv('SLACK_BOT_TOKEN')}"}
            )
            file_content = response.content

            files.append(File(
                url=file.get("url_private", ""),
                name=file.get("name", ""),
                filetype=file.get("filetype", ""),
                content=file_content
            ))

        return files

    def upload_files(self, files: List[File], client, max_retries=5) -> List[str]:
        """Upload files to Slack and return URLs"""
        urls = []
        for file in files:
            try:
                # Upload file to slack
                upload_response = client.files_upload_v2(
                    file=file.content,
                    filename=file.name
                )

                # Get initial file data
                file_data = upload_response.get('file')
                if not file_data:
                    print(f"No file data received for {file.name}")
                    continue

                # Wait for file to be fully processed
                attempts = 0
                while not file_data.get('mimetype'):
                    attempts += 1
                    if attempts >= max_retries:
                        print(f"Gave up waiting for file {file.name} after {attempts} seconds")
                        break

                    time.sleep(1)
                    file_info = client.files_info(file=file_data['id'])
                    file_data = file_info.get('file')
                    print(f"Waiting for file {file.name}, attempt {attempts}")

                if file_data.get('mimetype'):
                    print(f"File ready after {attempts}s: {file.name}")
                    urls.append(file_data['url_private'])

            except Exception as e:
                print(f"Failed to upload file: {str(e)}")
                continue

        return urls

    def handle_mention(self, event, say, client):
        """Handle @mentions of the bot"""
        self._send_ack(event, client)

        channel_info = client.conversations_info(channel=event['channel'])

        user_info = client.users_info(user=event['user'])
        email = user_info['user']['profile']['email']

        # Handle any files attached to the message
        files = self._process_files(event, client)

        message = ApplicationMessage(
            user=email,
            text=event['text'],
            application="Slack",
            files=files
        )

        try:
            text, images = self.message_handler.handle_message(message)
        except Exception as e:
            print(f"Error in message handler: {str(e)}")

        if images:
            # attachments = self.upload_files(images, client)
            attachments = [file.url for file in images]
        else:
            attachments = None

        formatted_msg = self._format_msg(text, attachments=attachments)

        say(formatted_msg)

    def handle_app_home_opened(self, client, event):
        """Handle app home opened events"""
        team_info = client.team_info()
        self.workspace_info = {
            'name': team_info['team']['name'],
            'email': team_info['team']['email_domain']
        }

    def handle_channel_join(self, event, say, client):
        """Handle bot being added to channels"""
        if event.get("user") == client.auth_test()["user_id"]:
            say("Thanks for adding me! Happy to be of service.")

    def handle_help_command(self, ack, respond, command):
        """Handle /bothelp command"""
        ack()
        respond("""Here's what I can do:
        - Respond to DMs
        - Reply when @mentioned
        - See all messages in channels I'm in
        - Use /bothelp for this help message
        """)

    @property
    def message_handler(self) -> MessageHandler:
        if self._message_handler is None:
            raise ValueError("No message handler set")
        return self._message_handler

    @message_handler.setter
    def message_handler(self, handler: MessageHandler):
        if not hasattr(handler, 'handle_message'):
            raise ValueError("Handler must implement handle_message")
        self._message_handler = handler

    def _send_ack(self, event, client):
        # Respond with "watching" emoji
        client.reactions_add(
            channel=event['channel'],
            name="eyes",
            timestamp=event['ts']
        )

    def _format_msg(self, text, attachments=None):
        # remove lines with URLs that are in the attachments from the text
        if attachments:
            text = "\n".join([line for line in text.split("\n") if not any(url in line for url in attachments)])

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text
                }
            }
        ]

        if attachments:
            for url in attachments:
                # Add a divider before each image
                blocks.append({"type": "divider"})
                blocks.append({
                    "type": "image",
                    "image_url": url,
                    "alt_text": "Generated image"
                })

        return {
            "text": text,
            "blocks": blocks
        }

    def _handle_dm(self, event, say, client):
        """Handle direct messages"""
        self._send_ack(event, client)

        user_info = client.users_info(user=event['user'])
        email = user_info['user']['profile']['email']

        # Handle any files attached to the message
        files = self._process_files(event, client)

        message = ApplicationMessage(
            user=email,
            text=event['text'],
            application="Slack",
            files=files
        )

        try:
            text, images = self.message_handler.handle_message(message)
        except Exception as e:
            print(f"Error in message handler: {str(e)}")

        if images:
            # attachments = self.upload_files(images, client)
            attachments = [file.url for file in images]
        else:
            attachments = None

        formatted_msg = self._format_msg(text, attachments=attachments)

        say(formatted_msg)

    def _handle_channel_message(self, event, say, client):
        """Handle messages in channels"""
        print(f"Saw message in channel: {event['text']}")

        # Get thread context
        thread_ts = event.get("thread_ts")
        if thread_ts:
            thread_messages = client.conversations_replies(
                channel=event['channel'],
                ts=thread_ts
            )
            print(f"Thread has {len(thread_messages['messages'])} messages")

        # Get channel history
        history = client.conversations_history(
            channel=event['channel'],
            limit=10
        )

        print(f"Channel history has {len(history['messages'])} messages")

    def start(self):
        """Start the bot"""
        handler = SocketModeHandler(self.app, os.environ["SLACK_APP_TOKEN"])
        handler.start()

# Usage
if __name__ == "__main__":
    bot = SlackBot()
    bot.start()