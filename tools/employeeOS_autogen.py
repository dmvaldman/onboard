import os
import time
import json
import sys
import regex as re

from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Dict
from utils.imgur import file_upload as file_upload_imgur
from utils.classes import File, Message, ApplicationMessage

from agents.agent_autogen import Agent, File, MessageHandler
from tools.notion import tool_specs as tool_specs_notion, tool_maps as tool_maps_notion

from autogen.agentchat.contrib.gpt_assistant_agent import GPTAssistantAgent
from autogen import ConversableAgent, UserProxyAgent

load_dotenv('creds/.env', override=True)
assistant_id = os.environ.get("ASSISTANT_ID", None)


tool_spec_agent = [{
    "type": "function",
    "function": {
        "name": "chat_with_agent",
        "description": "Delegate a task to AI Analyst by providing a description and any necessary attachments (file IDs).",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The description of the task."
                },
                "file_ids": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "description": "Identifier for the uploaded file."
                    },
                    "description": "File IDs"
                }
            },
            "required": ["text"],
            "additionalProperties": False
        }
    }
}]


class EmployeeOS(GPTAssistantAgent):
    def __init__(self, agent):

        name = "Employee"

        llm_config = {
            "model": "gpt-4o-mini",
            "api_key": os.getenv('OPENAI_API_KEY')
        }

        assistant_config = {
            "assistant_id": assistant_id,
            "tools": tool_spec_agent + tool_specs_notion
        }

        super().__init__(
            name=name,
            instructions=f"""You are a generalist employee.
                You have access to various communication tools like Notion and Slack.
                You have access to an AI Analyst for any analytical work.
                Delegate any analytical work to your AI Analyst.""",
            llm_config=llm_config,
            assistant_config=assistant_config,
            verbose=True)

        self.agent = agent
        self.agent_attachments: List[str] = []

        tool_maps_agent = {"chat_with_agent": self.chat_with_agent}
        self.register_function(function_map=tool_maps_agent | tool_maps_notion)

    def add_files(self, files: List[File]) -> List[str]:
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

    def download_file(self, file_id, upload=False) -> File:
        try:
            response = self.openai_client.files.with_raw_response.retrieve_content(file_id)
            return File(
                name=file_id,
                filetype="image",
                content=response.content
            )
        except Exception as e:
            print(f"Error retrieving file {file_id}: {e}")

    def upload_file_public(self, file: File):
        res = file_upload_imgur(file.content)
        file.url = res['url']
        file.id = res['id']
        return res

    def parse_files_in_response(self, response, upload=True):
        ids = re.findall(r'file-[^\n]+', response)
        files = []
        file_map = {}
        for file_id in ids:
            file = self.download_file(file_id)
            if upload: self.upload_file_public(file)
            files.append(file)
            file_map[file_id] = file.url

        if files:
            agent_file_ids = self.add_files(files)
            self.agent_attachments.extend(files)

        # Replace file ids with urls in the response
        response = re.sub(r'file-[^\n]+', lambda x: file_map[x.group()], response)

        return response

    def chat_with_agent(self, text, file_ids=None):
        # TODO: all chats with agent start from scratch
        if file_ids:
            print('Files sent to agent: ', file_ids)
            self.agent.add_files(file_ids)
            attachment_str = [{"file_id": file_id, "tools": [{"type": "code_interpreter"}]} for file_id in file_ids]
            message = {
                "role": "user",
                "content": text,
                "attachments": attachment_str
            }
        else:
            print('No files sent to agent.')
            message = {"role": "user", "content": text}

        response = self.initiate_chat(recipient=self.agent, message=message, max_turns=1)

        summary = self.parse_files_in_response(response.summary)
        return summary

    def handle_message(self, message: ApplicationMessage) -> tuple([str, List[File]]):
        content = message.text
        files = message.files

        self.agent_attachments = [] # Clear attachments

        if files:
            file_ids = self.add_files(files)
            file_names = [file.name for file in files]
            file_str = f"Files successfully uploaded. Filenames: {', '.join(file_names)} with IDs: {', '.join(file_ids)}"
            attachment_str = [{"file_id": file_id, "tools": [{"type": "code_interpreter"}]} for file_id in file_ids]

            messages = [{
                    "role": "user",
                    "content": content,
                    # "content": file_str + '\n\n' + content
                    # "attachments": attachment_str
                }]
        else:
            messages = [{"role": "user", "content": content}]

        response = self.generate_reply(messages=messages)

        return response['content'], self.agent_attachments


if __name__ == "__main__":
    agent = Agent("AI Analyst", "I am an senior data analyst here to help you answer questions.")
    employee = EmployeeOS(agent)
    sender = "Dave"

    # Create ApplicationMessage with file attachment from assets/dataset.csv
    with open("assets/dataset.csv", "rb") as f:
        file = File(
            name="dataset.csv",
            filetype="csv",
            content=f.read()
        )

    files = [file]

    message = ApplicationMessage(
        text="Analyze this CSV and generate a pie chart of the product categories.",
        files=files
    )

    # response = employee.handle_message(message, slack_user)
    response, files = employee.handle_message(message)
    print('\n-----------------\n\nFinal Response:\n\n', response)
