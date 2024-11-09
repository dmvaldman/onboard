import os
import time
import json

from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Dict, Protocol
from dataclasses import dataclass, field
from tools.notion import tool_specs as tool_specs_notion, tool_maps as tool_maps_notion

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

        # Add Notion tool
        self.tool_maps = tool_maps_notion
        self.add_tools(tool_specs_notion)

    def add_tools(self, tool_specs: List[Dict]):
        """Add a tool to the assistant"""
        self.assistant = self.client.beta.assistants.update(
            assistant_id=self.assistant.id,
            tools=self.assistant.tools + tool_specs
        )

    def add_files(self, files):
        """Upload files to the assistant"""
        file_ids = []
        for file in files:
            uploaded_file = self.client.files.create(
                file=file.content,
                purpose='assistants'
            )
            file_ids.append(uploaded_file.id)

        # Update the assistant's code interpreter with the new files
        self.assistant = self.client.beta.assistants.update(
            assistant_id=self.assistant.id,
            tools=self.assistant.tools,
            tool_resources={
                "code_interpreter": {
                    "file_ids": file_ids
                }
            })

    def run_tool(self, run, thread_id, tool_maps):
        tool_outputs = []
        for tool in run.required_action.submit_tool_outputs.tool_calls:
            if tool.function.name in tool_maps:
                tool_function = tool_maps[tool.function.name]
                args = json.loads(tool.function.arguments)
                output = tool_function(**args)
                tool_outputs.append({
                    "tool_call_id": tool.id,
                    "output": str(output)
                })
            else:
                print(f"Tool {tool.function.name} not found in tool maps.")

        try:
            self.client.beta.threads.runs.submit_tool_outputs_and_poll(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )
            print("Tool outputs submitted successfully.")
        except Exception as e:
            print("Failed to submit tool outputs:", e)
        else:
            print("No tool outputs to submit.")

    def handle_message(self, message: ApplicationMessage) -> str:
        user_id = message.user
        content = message.text

        try:
            # Upload any files first
            if message.files:
                self.add_files(message.files)

            # Create thread with just the text message
            if user_id not in self.threads:
                thread = self.client.beta.threads.create(
                    messages=[{"role": "user", "content": content}]
                )
                self.threads[user_id] = thread.id
            else:
                # Add message to existing thread
                self.client.beta.threads.messages.create(
                    thread_id=self.threads[user_id],
                    role="user",
                    content=content
                )

            thread_id = self.threads[user_id]

            # Run the assistant
            run = self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=self.assistant.id
            )

            # Wait for completion
            while True:
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )

                status = run.status
                print(f"Run status: {status}")

                if status == 'completed':
                    break
                elif status == 'failed':
                    return f"Sorry, I encountered an error processing your request:\n{run.error}"
                elif status == "requires_action" and run.required_action.type == 'submit_tool_outputs':
                    self.run_tool(run, thread_id, self.tool_maps)

                time.sleep(1)

            # Get messages (newest first)
            messages = self.client.beta.threads.messages.list(
                thread_id=thread_id,
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