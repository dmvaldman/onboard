import os
import time
import json

from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Dict, Protocol, Union
from dataclasses import dataclass, field

load_dotenv('creds/.env', override=True)

@dataclass
class File:
    name: str
    filetype: str
    content: bytes = field(repr=False)

@dataclass
class Message:
    text: str
    files: List[File] = field(default_factory=list)

class MessageHandler(Protocol):
    def handle_message(self, message: Message) -> str:
        pass

class Agent(MessageHandler):
    def __init__(self, name, instructions, model="gpt-4o-mini", force=False):
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

        # Create or load assistant
        self.assistant = self.create_assistant(name, instructions, model=model, force=force)

        self.name = name
        self.instructions = instructions

        # Track threads per user
        self.thread_id = None

    def create_assistant(self, name, instructions, model="gpt-4o-mini", force=False):
        # if not force:
        #     assistants = self.client.beta.assistants.list(limit=100).data
        #     for assistant in assistants:
        #         if assistant.name == name:
        #             return assistant

        return self.client.beta.assistants.create(
            name=name,
            instructions=instructions,
            tools=[{"type": "code_interpreter"}],
            model=model
        )

    def add_files(self, files: List[Union[File, str]]) -> List[str]:
        """Upload files to the assistant"""

        # If files are File objects, upload them
        if isinstance(files[0], File):
            file_ids = []
            for file in files:
                uploaded_file = self.client.files.create(
                    file=file.content,
                    purpose='assistants'
                )
                file_ids.append(uploaded_file.id)

        else:
            # Assume files are already uploaded
            file_ids = files

        # Update the assistant's code interpreter with the new files
        self.assistant = self.client.beta.assistants.update(
            assistant_id=self.assistant.id,
            tools=self.assistant.tools,
            tool_resources={
                "code_interpreter": {
                    "file_ids": file_ids
                }
            })

        return file_ids

    def process_attachment(self, file_id) -> Dict:
        res = self.client.files.with_raw_response.retrieve_content(file_id)

        return {
            "file_id": file_id,
            "content": res.content
        }

    def handle_message(self, message: Message) -> tuple[str, List]:
        content = message.text

        print(f'{self.name} received message: "{content}"')

        try:
            # # Upload any files first
            # if message.files:
            #     self.add_files(message.files)

            # Create thread with just the text message
            if self.thread_id is None:
                thread = self.client.beta.threads.create(
                    messages=[{"role": "user", "content": content}]
                )
                self.thread_id = thread.id
            else:
                # Add message to existing thread
                self.client.beta.threads.messages.create(
                    thread_id=self.thread_id,
                    role="user",
                    content=content
                )

            # Run the assistant
            run = self.client.beta.threads.runs.create(
                thread_id=self.thread_id,
                assistant_id=self.assistant.id
            )

            # Wait for completion
            while True:
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=self.thread_id,
                    run_id=run.id
                )

                status = run.status
                print(f"Run status for {self.name}: {status}")

                if status == 'completed':
                    break
                elif status == 'incomplete':
                    return f"Sorry, I encountered an error processing your request:\n{run.incomplete_details}"
                elif status == 'failed':
                    return f"Sorry, I encountered an error processing your request:\n{run.error}"

                time.sleep(1)

            # Get messages (newest first)
            messages = self.client.beta.threads.messages.list(
                thread_id=self.thread_id,
            )

            # Return the assistant's last response
            response_text = ""
            attachments = []
            for msg in reversed(messages.data):
                if msg.role != "assistant":
                    continue

                # Extract text from all content blocks
                for content in msg.content:
                    if content.type == 'text':
                        # Collect text
                        response_text += content.text.value
                    elif content.type == 'image_file':
                        file_id = content.image_file.file_id
                        attachment = self.process_attachment(file_id)
                        attachments.append(attachment)
                response_text += "\n\n\n"

            return response_text, attachments

        except Exception as e:
            print(f"Error in {self.name} assistant response: {e}")
            return f"Sorry, I encountered an error: {str(e)}"

    def reset_conversation(self, user_id: str):
        """Start a new thread for the user"""
        # Create new thread
        thread = self.client.beta.threads.create()
        self.thread_id = thread.id


if __name__ == "__main__":
    agent = Agent(
        "AI Analyst",
        "I am an senior data analyst here to help you answer questions."
    )

    # Create ApplicationMessage with file attachment from assets/dataset.csv
    with open("assets/dataset.csv", "rb") as f:
        file = File(
            name="dataset.csv",
            filetype="csv",
            content=f.read()
        )

    file_ids = agent.add_files([file])

    msg = Message(
        text="Please analyze this CSV and report any trends or anomalous behavior",
        files=[file]
    )

    response = agent.handle_message(msg)
    print(response)