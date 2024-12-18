import time

from comms.slack import SlackBot
from comms.notion import NotionBot

# from agents.agent import Agent
# from tools.employeeOS import EmployeeOS

from agents.agent_autogen import Agent
from tools.employeeOS_autogen import EmployeeOS

from utils.delete import delete_assistants_and_files
delete_assistants_and_files()

# Agent
agent = Agent(
    "AI Analyst",
    "I am an senior data analyst here to help you answer questions. My responses may use markdown, but no other syntax, like latex, mathml, etc.",
    model="gpt-4o"
)
employee = EmployeeOS(agent)

# Comms
slackbot = SlackBot()
notionbot = NotionBot()

slackbot.message_handler = employee
notionbot.message_handler = employee

slackbot.start()
notionbot.start()

while True:
    time.sleep(1)