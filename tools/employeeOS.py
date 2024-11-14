import os
import time
import json
import sys

from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Dict, Protocol
from dataclasses import dataclass, field

from agents.agent import Agent, File, MessageHandler
from tools.notion import tool_specs as tool_specs_notion, tool_maps as tool_maps_notion

load_dotenv('creds/.env', override=True)


@dataclass
class Message:
    text: str
    files: List[str] = field(default_factory=list)

@dataclass
class ApplicationMessage():
    user: str
    application: str
    text: str
    files: List[File] = field(default_factory=list)

tool_spec_agent = [{
    "type": "function",
    "function": {
        "name": "chat_with_agent",
        "description": "Delegate a task to AI Analyst by providing a description and any necessary files.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The description of the task."
                },
                "files": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "description": "File ID"
                    },
                    "description": "File IDs"
                }
            },
            "required": ["text"],
            "additionalProperties": False
        }
    }
}]

class EmployeeOS(MessageHandler):
    def __init__(self, agent, model="gpt-4o-mini", force=False):
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

        instructions = f"""You are a generalist employee.
        You have access to various communication tools like Notion and Slack.
        You have access to an AI Analyst for any analytical work.
        Delegate any analytical work to your AI Analyst and forward their response back to the user verbatim.
        Do not provide any links to any attached files, file attaching will be handled by a separate system."""

        self.agent = agent
        self.name = "Employee"
        self.instructions = instructions
        self.agent_attachments = []

        # Create or load assistant
        self.assistant = self.create_assistant(self.name, instructions, model=model, force=force)

        # Track threads per user
        self.threads: Dict[str, str] = {}

        tool_maps_agent = {"chat_with_agent": self.chat_with_agent}

        tool_maps = tool_maps_agent | tool_maps_notion
        tools = tool_spec_agent + tool_specs_notion

        self.tool_maps = tool_maps
        self.add_tools(tools)

    def create_assistant(self, name, instructions, model="gpt-4o-mini", force=False):
        # Create or load assistant if name already exists
        # if not force:
        #     assistants = self.client.beta.assistants.list(limit=100).data
        #     for assistant in assistants:
        #         if assistant.name == name:
        #             return assistant

        return self.client.beta.assistants.create(
            name="Employee",
            instructions=instructions,
            tools=[{"type": "code_interpreter"}, {"type": "file_search"}],
            model=model
        )

    def add_tools(self, tool_specs: List[Dict]):
        """Add a tool to the assistant"""
        self.assistant = self.client.beta.assistants.update(
            assistant_id=self.assistant.id,
            tools=self.assistant.tools + tool_specs
        )

    def add_files(self, files: List[File], thread_id):
        """Upload files to the assistant"""
        file_ids = []
        for file in files:
            uploaded_file = self.client.files.create(
                file=file.content,
                purpose='assistants'
            )
            file_ids.append({"id": uploaded_file.id, "name": file.name})

        # try:
        #     file_ids = self.agent.add_files(files)

        self.client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=f"<log start> Files {file_ids} successfully uploaded. <log end>"
        )

        print(f"<log start> Files {file_ids} successfully uploaded. <log end>")
        # except Exception as e:
        #     print(f"Error uploading files: {e}")

        return file_ids

    def chat_with_agent(self, **kwargs) -> tuple([str, List]):
        message = Message(**kwargs)

        if message.files:
            self.agent.add_files(message.files)

        response_text, attachments = self.agent.handle_message(message)
        self.agent_attachments.extend(attachments)

        if attachments:
            response_text += "Attachments (These will be automatically sent to the user in your followup reply. Do not reference these.):"
            for attachment in attachments:
                response_text += f"\n{attachment['file_id']}"

        return response_text

    def run_tool(self, run, thread_id):
        tool_outputs = []
        for tool in run.required_action.submit_tool_outputs.tool_calls:
            if tool.function.name in self.tool_maps:
                tool_function = self.tool_maps[tool.function.name]
                args = json.loads(tool.function.arguments)
                print(f"{self.name} - Calling `{tool.function.name}` (tool_id {tool.id}) with args: {args}")

                output = tool_function(**args)
                print(f"{self.name} - Output: {output}")

                tool_outputs.append({
                    "tool_call_id": tool.id,
                    "output": str(output)
                })
            else:
                print(f"Tool {tool.function.name} not found in tool maps.")

        if tool_outputs:
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

    def process_attachment(self, file_id) -> Dict:
        try:
            response = self.client.files.with_raw_response.retrieve_content(file_id)
        except Exception as e:
            print(f"Error retrieving file {file_id}: {e}")

        attachment = {
            "file_id": file_id,
            "content": response.content
        }
        return attachment

    def handle_message(self, message: ApplicationMessage) -> str:
        user_id = message.user
        content = message.text

        print(f'{self.name} received message from {user_id}: "{content}"')

        try:
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

            thread_id = self.threads[user_id]

            # Upload any files
            if message.files:
                self.add_files(message.files, thread_id)

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
                print(f"Run status for {self.name}: {status}")

                if status == 'completed':
                    break
                elif status == 'incomplete':
                    raise Exception(f"Status {status}. I encountered an error processing your request:\n{run.incomplete_details}")
                elif status == 'failed':
                    raise Exception(f"Status {status}. I encountered an error processing your request:\n{run.error}")
                elif status == "requires_action" and run.required_action.type == 'submit_tool_outputs':
                    self.run_tool(run, thread_id)

                time.sleep(1)

            # Get messages (newest first)
            messages = self.client.beta.threads.messages.list(
                thread_id=thread_id,
            )

            # Return the assistant's last response
            response_text = ""
            images = []
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
                        image = self.process_attachment(file_id)
                        images.append(image)
                response_text += "\n\n\n"

            # Add any attachments from the agent
            while self.agent_attachments:
                images.append(self.agent_attachments.pop())

            print(f"{self.name} response: {response_text}")

            return response_text, images

        except Exception as e:
            print(f"Error in {self.name} assistant response: {e}")
            return f"Sorry, I encountered an error: {str(e)}"

    def reset_conversation(self, user_id: str):
        """Start a new thread for the user"""
        if user_id in self.threads:
            # Create new thread
            thread = self.client.beta.threads.create()
            self.threads[user_id] = thread.id


if __name__ == "__main__":
    agent = Agent("AI Analyst", "I am an senior data analyst here to help you answer questions.")
    employee = EmployeeOS(agent)

    # Create ApplicationMessage with file attachment from assets/dataset.csv
    with open("assets/dataset.csv", "rb") as f:
        file = File(
            name="dataset.csv",
            filetype="csv",
            content=f.read()
        )

    msg = ApplicationMessage(
        user="Dave",
        application="Slack",
        text="Analyze this CSV and generate a pie chart of the product categories.",
        files=[file])

    response, attachments = employee.handle_message(msg)
    print('\n-----------------\n\nFinal Response:\n\n', response)
