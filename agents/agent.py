import os
import time

from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Dict, Protocol
from dataclasses import dataclass, field

load_dotenv('creds/.env', override=True)

@dataclass
class File:
    """Represents a file uploaded to Slack"""
    url: str
    name: str
    filetype: str
    content: bytes = field(repr=False)

@dataclass
class ApplicationMessage:
    text: str
    user: str
    application: str
    files: List[File] = field(default_factory=list)

class MessageHandler(Protocol):
    def handle_message(self, message: ApplicationMessage) -> str:
        pass

class Agent:
    def __init__(self, name, system_prompt, model="gpt-4o"):
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

        # Create or load assistant
        self.assistant = self.client.beta.assistants.create(
            name=name,
            instructions=system_prompt,
            tools=[{"type": "code_interpreter"}],
            model=model
        )

        # Track threads per user
        self.threads: Dict[str, str] = {}

    def handle_message(self, message: ApplicationMessage) -> str:
        user_id = message.user
        content = message.text

        try:
            # Upload any files first
            if message.files:
                file_ids = []
                for file in message.files:
                    uploaded_file = self.client.files.create(
                        file=file.content,
                        purpose='assistants'
                    )
                    file_ids.append(uploaded_file.id)

                # Update the assistant's code interpreter with the new files
                self.client.beta.assistants.update(
                    assistant_id=self.assistant.id,
                    tools=[{"type": "code_interpreter"}],
                    tool_resources={
                        "code_interpreter": {
                            "file_ids": file_ids
                        }
                    }
                )

            # Create thread with just the text message
            if user_id not in self.threads:
                thread = self.client.beta.threads.create(
                    messages=[{
                        "role": "user",
                        "content": content
                    }]
                )
                self.threads[user_id] = thread.id
            else:
                # Add message to existing thread
                self.client.beta.threads.messages.create(
                    thread_id=self.threads[user_id],
                    role="user",
                    content=content
                )

            # Run the assistant
            run = self.client.beta.threads.runs.create(
                thread_id=self.threads[user_id],
                assistant_id=self.assistant.id
            )

            # Wait for completion
            while True:
                run_status = self.client.beta.threads.runs.retrieve(
                    thread_id=self.threads[user_id],
                    run_id=run.id
                )
                if run_status.status == 'completed':
                    break
                elif run_status.status == 'failed':
                    return f"Sorry, I encountered an error processing your request:\n{run_status.error}"
                time.sleep(1)

            # Get messages (newest first)
            messages = self.client.beta.threads.messages.list(
                thread_id=self.threads[user_id]
            )

            # Return the assistant's last response
            for msg in messages.data:
                if msg.role == "assistant":
                    # Extract text from all content blocks
                    response_text = ""
                    for content in msg.content:
                        if content.type == 'text':
                            response_text += content.text.value
                    return response_text if response_text else "No text response generated."


            return "No response generated."

        except Exception as e:
            print(f"Error in assistant response: {e}")
            return f"Sorry, I encountered an error: {str(e)}"

    def reset_conversation(self, user_id: str):
        """Start a new thread for the user"""
        if user_id in self.threads:
            # Create new thread
            thread = self.client.beta.threads.create()
            self.threads[user_id] = thread.id


if __name__ == "__main__":
    agent = Agent("AI Analyst", "I am an senior data analyst here to help you answer questions.")

    user_id = "Dave"
    content = "What is 1+1?"
    application = "Slack"
    message = ApplicationMessage(content, user_id, application)

    print(agent.handle_message(message))