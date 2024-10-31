from comms.slack import SlackBot
from agents.agent import Agent, MessageHandler


if __name__ == "__main__":
    agent = Agent(
        "AI Analyst",
        "I am an senior data analyst here to help you answer questions. My responses may use markdown, but no other syntax, like latex, mathml, etc."
    )

    slackbot = SlackBot()

    slackbot.message_handler = agent
    slackbot.start()