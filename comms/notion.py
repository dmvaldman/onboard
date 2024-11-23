import dotenv
import os
import requests
import mistune
from datetime import datetime, timedelta
import threading
import queue
import time


from notion_client import Client
from agents.agent import MessageHandler
from comms.base import CommsBotBase
from utils.classes import ApplicationMessage


dotenv.load_dotenv('creds/.env')

class NotionBot(CommsBotBase):
    def __init__(self):
        self.client = Client(auth=os.environ["NOTION_TOKEN"])
        self._message_handler: MessageHandler = None
        self.comment_queue = queue.Queue()
        self.processed_comment_ids = set()

    def get_block_comments(self, block_id):
        try:
            comments = self.client.comments.list(block_id=block_id)
            return comments.get("results", [])
        except Exception as e:
            print(f"Error getting comments: {e}")
            return []

    def get_page_comments(self, page_id):
        # Get top-level comments
        top_level_comments = self.get_block_comments(page_id)

        # Get all blocks in the page
        all_blocks = []
        has_more = True
        start_cursor = None

        while has_more:
            if start_cursor:
                response = self.client.blocks.children.list(block_id=page_id, start_cursor=start_cursor)
            else:
                response = self.client.blocks.children.list(block_id=page_id)

            all_blocks.extend(response["results"])
            has_more = response["has_more"]
            if has_more:
                start_cursor = response["next_cursor"]

        # Get comments for each block
        inline_comments = []
        for block in all_blocks:
            block_comments = self.get_block_comments(block["id"])
            if block_comments:
                inline_comments.extend(block_comments)

        return top_level_comments + inline_comments

    def get_all_pages(self):
        """Retrieve all pages in the organization"""
        all_pages = []
        has_more = True
        start_cursor = None

        while has_more:
            response = self.client.search(
                filter={"property": "object", "value": "page"},
                start_cursor=start_cursor
            )
            all_pages.extend(response.get("results", []))
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

        return all_pages

    def get_pages_after(self, date=None):
        """Retrieve all pages updated after a certain date, or all pages if date is None"""
        all_pages = []
        has_more = True
        start_cursor = None

        # Convert the date to ISO 8601 format if provided
        iso_date = date.isoformat() if date else None

        while has_more:
            response = self.client.search(
                filter={
                    "property": "object",
                    "value": "page"
                },
                sort={
                    "direction": "descending",
                    "timestamp": "last_edited_time"
                },
                start_cursor=start_cursor
            )

            # Filter pages by last_edited_time if a date is provided
            pages = response.get("results", [])
            for page in pages:
                last_edited_time = page["last_edited_time"]
                if not iso_date or last_edited_time > iso_date:
                    all_pages.append(page)

            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

        return all_pages

    def get_block_content(self, block_id):
        """Retrieve the content of a block by its ID"""
        try:
            block = self.client.blocks.retrieve(block_id)
            # Initialize an empty string to accumulate content
            content = ""

            # Extract the content based on block type
            if block["type"] == "image":
                image_data = block["image"]
                if image_data["type"] == "external":
                    content = image_data["external"]["url"]
                elif image_data["type"] == "file":
                    content = image_data["file"]["url"]
            else:
                # Catch-all for other block types with rich_text
                rich_text_key = block.get(block["type"], {}).get("rich_text", [])
                for rich_text in rich_text_key:
                    content += rich_text["text"]["content"]

            return content
        except Exception as e:
            print(f"Error retrieving block content: {e}")
            return "Error retrieving content"

    def get_page_title(self, page_id):
        """Retrieve the title of a page"""
        try:
            page = self.client.pages.retrieve(page_id)
            properties = page.get("properties", {})

            # Assuming the title is stored in a property named "Title"
            for prop_name, prop_value in properties.items():
                if prop_value.get("type") == "title":
                    title_parts = prop_value.get("title", '')
                    # Concatenate all parts of the title
                    title = ''.join([part.get("text", {}).get("content", '') for part in title_parts])
                    return title
            return ""
        except Exception as e:
            print(f"Error retrieving page title: {e}")
            return "Error retrieving title"

    def get_page_text_content(self, page_id):
        """Retrieve the text content of a page by iterating over its blocks"""
        all_text_content = []
        has_more = True
        start_cursor = None

        title = self.get_page_title(page_id)

        while has_more:
            response = self.client.blocks.children.list(block_id=page_id, start_cursor=start_cursor)
            blocks = response.get("results", [])
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

            for block in blocks:
                block_id = block["id"]
                block_content = self.get_block_content(block_id)
                all_text_content.append(f"Block ID: {block_id}\n{block_content}")
                # if block["type"] == "image":
                #     image_data = block["image"]
                #     if image_data["type"] == "external":
                #         all_text_content.append(image_data["external"]["url"])
                # else:
                #     # Catch all for other block types with rich_text
                #     type = block["type"]
                #     rich_text_key = block.get(type, {}).get("rich_text", [])
                #     for rich_text in rich_text_key:
                #         all_text_content.append(rich_text["text"]["content"])

        return title + "\n\n".join(all_text_content)

    def get_page_comments_for_agent(self, page_id):
        comments = self.get_page_comments(page_id)
        agent_name = self.message_handler.agent.name

        if not comments:
            return []

        comments_to_address = []

        # loop through comments, once there's mention of the AI Analyst, grab the next block
        for comment in comments:
            discussion_id = comment['discussion_id']
            comment_id = comment['id']
            created_by_user_id = comment['created_by']['id']
            grab_next_block = False
            for block in comment['rich_text']:
                if block['type'] == "mention":
                    if block['mention']['user']['name'] == agent_name:
                        grab_next_block = True
                elif grab_next_block:
                    content = block['text']['content']
                    sender = self.client.users.retrieve(created_by_user_id)
                    sender_email = sender['person']['email']
                    anchor_block_id =comment['parent']['block_id']

                    context_anchor = self.get_block_content(anchor_block_id)
                    context_page = self.get_page_text_content(page_id)

                    comments_to_address.append({
                        "page_id": page_id,
                        "sender_email": sender_email,
                        "id": comment_id,
                        "discussion_id": discussion_id,
                        "block_id": anchor_block_id,
                        "content": content,
                        "context_block": context_anchor,
                        "context_page": context_page,
                    })

                    grab_next_block = False

        return comments_to_address

    def poll_for_comments(self, interval=300):
        """Long poll for new pages updated since the last poll"""
        agent_name = self.message_handler.agent.name

        while True:
            print("Polling for new Notion comments...")
            pages = self.get_all_pages()
            for page in pages:
                comments = self.get_page_comments_for_agent(page['id'])
                for comment in comments:
                    comment_id = comment['id']
                    if comment_id not in self.processed_comment_ids:
                        print(f"Adding new comment from page {page['id']}")
                        self.comment_queue.put(comment)
                        self.processed_comment_ids.add(comment_id)

            # Wait before polling again
            time.sleep(interval)

    def respond_to_comments(self, interval=300):

        def format_comment(comment):
            text = f"Please address this comment on the Notion page {comment['page_id']}. To address the comment, update the relevant portions of the page and reply with a brief summary of the resolution (1-3 sentences). Below is relevant context followed by the user's comment.\n<START CONTEXT>\n\nPage context: {comment['context_page']}\nBlock ID: {comment['block_id']}\nBlock text: {comment['context_block']}\n<END CONTEXT>\nComment from {comment['sender_email']}: {comment['content']}"
            message = ApplicationMessage(
                user=comment['sender_email'],
                text=text,
                application="Notion",
                files=None
            )
            return message


        while True:
            while not self.comment_queue.empty():
                comment = self.comment_queue.get()
                print(f"Received comment: {comment}")

                try:
                    print(f"Processing comment: {comment['id']} from {comment['sender_email']} on page {comment['page_id']}")

                    # Process the comment
                    discussion_id = comment['discussion_id']
                    message = format_comment(comment)
                    text, attachments = self.message_handler.handle_message(message)

                    # Post response to Notion
                    response = self.client.comments.create(
                        discussion_id=discussion_id,
                        rich_text=[{"type": "text", "text": {"content": text}}]
                    )

                    print(f"Posted response: {response}")
                except Exception as e:
                    print(f"Error processing comment: {e}")
                finally:
                    self.comment_queue.task_done()

            # Wait before polling again
            time.sleep(interval)

    def start(self, interval=300):
        # Start the polling thread
        polling_thread = threading.Thread(target=self.poll_for_comments, args=(interval,))
        polling_thread.daemon = True
        polling_thread.start()

        # Start the response thread
        response_thread = threading.Thread(target=self.respond_to_comments, args=(interval,))
        response_thread.daemon = True
        response_thread.start()

        # Keep the main thread alive
        while True:
            time.sleep(1)

if __name__ == "__main__":
    from agents.agent_autogen import Agent
    from tools.employeeOS_autogen import EmployeeOS

    agent = Agent(
        "AI Analyst",
        "I am an senior data analyst here to help you answer questions. My responses may use markdown, but no other syntax, like latex, mathml, etc."
    )

    employee = EmployeeOS(agent)
    notionbot = NotionBot()

    notionbot.message_handler = employee
    notionbot.start(interval=100)
