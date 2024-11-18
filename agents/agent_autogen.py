import os
import time
import json
import regex as re

from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Dict, Protocol, Union
from dataclasses import dataclass, field
from autogen.agentchat.contrib.gpt_assistant_agent import GPTAssistantAgent

load_dotenv('creds/.env', override=True)
assistant_id = os.environ.get("ASSISTANT_ID", None)

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

class Agent(GPTAssistantAgent):
    def __init__(self, name, instructions):
        llm_config = {
            "model": "gpt-4o-mini",
            "api_key": os.getenv('OPENAI_API_KEY')
        }

        assistant_config = {
            "assistant_id": assistant_id,
            "tools": [{"type": "code_interpreter"}]
        }

        super().__init__(
            name=name,
            instructions=instructions,
            llm_config=llm_config,
            assistant_config=assistant_config,
            verbose=True,)

    def add_files(self, files: List[Union[File, str]]) -> List[str]:
        """Upload files to the assistant"""

        # If files are File objects, upload them
        if isinstance(files[0], File):
            file_ids = []
            for file in files:
                uploaded_file = self.openai_client.files.create(
                    file=file.content,
                    purpose='assistants'
                )
                file_ids.append(uploaded_file.id)

        else:
            # Assume files are already uploaded
            file_ids = files

        # Update the assistant's code interpreter with the new files
        self._openai_assistant = self.openai_client.beta.assistants.update(
            assistant_id=self.openai_assistant.id,
            tools=self.openai_assistant.tools,
            tool_resources={
                "code_interpreter": {
                    "file_ids": file_ids
                }
            })

        return file_ids

    def process_attachment(self, file_id) -> Dict:
        try:
            response = self.openai_client.files.with_raw_response.retrieve_content(file_id)
        except Exception as e:
            print(f"Error retrieving file {file_id}: {e}")

        return response.content


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

    file_id = agent.add_files([file])[0]

    message = {
        "role": "user",
        "content": "Analyze this CSV and generate a pie chart of the product categories.",
        "attachments": [
            {
                "file_id": file_id,
                "tools": [{"type": "code_interpreter"}]
            }
        ]
    }

    response = agent.generate_reply(messages=[message])

    # regex to extract file-cPfj1AAgX7SJaMYcIzJIAB0 from text
    file_id = "file-" + re.search(r'file-(\w+)', response['content']).group(1)
    if len(file_id) > 5:
        img_bytes = agent.process_attachment(file_id)
        with open("output.png", "wb") as f:
            f.write(img_bytes)

    print(response)