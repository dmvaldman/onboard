from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict
import time

from typing import Protocol
from dataclasses import dataclass

@dataclass
class ApplicationMessage:
    text: str
    user: str
    application: str

class MessageHandler(Protocol):
    def handle_message(self, message: ApplicationMessage) -> str:
        pass

load_dotenv('creds/.env')

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
            # Get or create thread for this user
            if user_id not in self.threads:
                thread = self.client.beta.threads.create()
                self.threads[user_id] = thread.id

            thread_id = self.threads[user_id]

            # Add message to thread
            self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=content
            )

            # Run the assistant
            run = self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=self.assistant.id
            )

            # Wait for completion
            while True:
                run_status = self.client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
                if run_status.status == 'completed':
                    break
                elif run_status.status == 'failed':
                    return "Sorry, I encountered an error processing your request."
                time.sleep(1)

            # Get messages (newest first)
            messages = self.client.beta.threads.messages.list(
                thread_id=thread_id
            )

            # Return the assistant's last response
            for msg in messages.data:
                if msg.role == "assistant":
                    return msg.content[0].text.value

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