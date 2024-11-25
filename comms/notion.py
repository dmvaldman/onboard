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
from utils.classes import ApplicationMessage, File


dotenv.load_dotenv('creds/.env')

class NotionBot(CommsBotBase):
    def __init__(self):
        super().__init__()
        self.client = Client(auth=os.environ["NOTION_TOKEN"])
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
            files = []

            # Extract the content based on block type
            if block["type"] == "image":
                image_data = block["image"]
                if image_data["type"] == "external":
                    url = image_data["external"]["url"]
                elif image_data["type"] == "file":
                    url = image_data["file"]["url"]
                content = url
                file = File(name=url, filetype="image", url=url)
                files.append(file)
            else:
                # Catch-all for other block types with rich_text
                rich_text_key = block.get(block["type"], {}).get("rich_text", [])
                for rich_text in rich_text_key:
                    content += rich_text["text"]["content"]

            return content, files
        except Exception as e:
            print(f"Error retrieving block content: {e}")
            return "Error retrieving content", None

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

    def get_page_content(self, page_id):
        """Retrieve the text content of a page by iterating over its blocks"""
        all_text_content = []
        all_images = []

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
                block_content, block_images = self.get_block_content(block_id)
                all_text_content.append(f"Block ID: {block_id}\nBlock Content: {block_content}")
                all_images.extend(block_images)

        text_content = "Title: " + title + "\n\n".join(all_text_content)
        return text_content, all_images

    def get_page_comments_for_agent(self, page):
        page_id = page['id']
        page_url = page['url']

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
            anchor_block_id = comment['parent']['block_id']

            has_mention = False
            content = ''
            for block in comment['rich_text']:
                if block['type'] == "mention" and block['mention']['user']['name'] == agent_name:
                    has_mention = True

                if block['type'] == "text":
                    content += block['text']['content']
                elif block['type'] == "mention":
                    continue
                else:
                    # TODO: Handle other block types
                    print(f"Received comment block type: {block['type']} which we do not yet support")

            if has_mention:
                sender = self.client.users.retrieve(created_by_user_id)
                sender_email = sender['person']['email']

                context_anchor, files_anchor = self.get_block_content(anchor_block_id)
                context_page, files_page = self.get_page_content(page_id)

                comments_to_address.append({
                    "page_url": page_url,
                    "page_id": page_id,
                    "sender_email": sender_email,
                    "id": comment_id,
                    "discussion_id": discussion_id,
                    "block_id": anchor_block_id,
                    "content": content,
                    "context_block": context_anchor,
                    "context_page": context_page,
                    "files_block": files_anchor,
                    "files_page": files_page
                })

        return comments_to_address

    def poll_for_comments(self, interval=300):
        """Long poll for new pages updated since the last poll"""
        agent_name = self.message_handler.agent.name

        while True:
            print("Polling for new Notion comments...")
            pages = self.get_all_pages()
            for page in pages:
                comments = self.get_page_comments_for_agent(page)
                for comment in comments:
                    comment_id = comment['id']
                    if comment_id not in self.processed_comment_ids:
                        print(f"Adding new comment from page {page['id']}")
                        self.comment_queue.put(comment)
                        self.processed_comment_ids.add(comment_id)

            # Wait before polling again
            time.sleep(interval)

    def respond_to_comments(self, interval=300):
        def download_files(files):
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
            }
            for file in files:
                try:
                    response = requests.get(file.url, headers=headers)
                    response.raise_for_status()  # Raise an error for bad responses
                    file.content = response.content
                except requests.exceptions.RequestException as e:
                    print(f"Error downloading file: {e}")
            return files

        def format_comment(comment):
            text = (
                f"Please address this comment on the Notion page with ID: {comment['page_id']} at URL {comment['page_url']}. "
                "To address the comment, update the relevant blocks on the page and reply with a brief summary "
                "(1-3 sentences) which will be used to reply to this comment. Context of the comment is provided below. We provide the full text of the page, the block which is the anchor of this comment, and the user info.\n\n"
                "<START CONTEXT>\n\n"
                f"<START PAGE CONTEXT>\n\n{comment['context_page']}\n\n<END PAGE CONTEXT>\n\n"
                f"<START ANCHOR BLOCK CONTEXT>\n\nBLOCK ID: {comment['block_id']}\n{comment['context_block']}\n\n<END ANCHOR BLOCK CONTEXT>\n\n"
                "<END CONTEXT>\n\n"
                f"Comment from {comment['sender_email']}: {comment['content']}"
            )


            files = comment['files_block'] if comment['files_block'] else comment['files_page']
            files = download_files(files)

            return ApplicationMessage(
                user=comment['sender_email'],
                text=text,
                application="Notion",
                files=files
            )

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

    # Keep the main thread alive
    while True:
        time.sleep(1)
