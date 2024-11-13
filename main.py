from comms.slack import SlackBot
from agents.agent import Agent, MessageHandler
from tools.employeeOS import EmployeeOS


if __name__ == "__main__":
    agent = Agent(
        "AI Analyst",
        "I am an senior data analyst here to help you answer questions. My responses may use markdown, but no other syntax, like latex, mathml, etc."
    )

    employee = EmployeeOS(agent)
    slackbot = SlackBot()

    slackbot.message_handler = employee
    slackbot.start()