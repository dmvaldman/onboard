import dotenv
import os
import requests
import mistune
from datetime import datetime, timedelta
import threading
import queue


from notion_client import Client
from agents.agent import MessageHandler


dotenv.load_dotenv('creds/.env')

class NotionRenderer:
    def __init__(self):
        self.blocks = []

    def render(self, markdown_text):
        markdown = mistune.create_markdown(renderer='ast')
        ast = markdown(markdown_text)
        self.blocks = self.process_nodes(ast)
        return self.blocks

    def process_nodes(self, nodes):
        blocks = []
        for node in nodes:
            blocks.extend(self.process_node(node))
        return blocks

    def process_node(self, node):
        node_type = node['type']
        if node_type == 'paragraph':
            blocks = self.process_inlines(node['children'], block_type='paragraph')
            return blocks
        elif node_type == 'heading':
            level = node['level']
            heading_type = f"heading_{level}"
            blocks = self.process_inlines(node['children'], block_type=heading_type)
            return blocks
        elif node_type == 'image':
            return [self.create_image_block(node)]
        elif node_type == 'list':
            blocks = []
            for item in node['children']:
                blocks.extend(self.process_node(item))
            return blocks
        elif node_type == 'list_item':
            list_type = 'bulleted_list_item' if not node.get('ordered') else 'numbered_list_item'
            blocks = self.process_inlines(node['children'], block_type=list_type)
            return blocks
        elif node_type == 'block_code':
            return [self.create_code_block(node)]
        else:
            # Handle other node types or ignore
            return []

    def process_inlines(self, inlines, block_type='paragraph'):
        blocks = []
        current_rich_text = []

        for inline in inlines:
            node_type = inline['type']
            if node_type == 'text':
                current_rich_text.append(self.create_text_rich_text(inline))
            elif node_type == 'image':
                # If we have accumulated rich_text, create a block
                if current_rich_text:
                    blocks.append(self.create_text_block(block_type, current_rich_text))
                    current_rich_text = []
                # Add the image block
                blocks.append(self.create_image_block(inline))
            elif node_type == 'link':
                text_elements = self.process_inlines(inline['children'], block_type=block_type)
                url = inline['destination']
                for block in text_elements:
                    if block['type'] == block_type:
                        for rt in block[block_type]['rich_text']:
                            rt['text']['link'] = {"url": url}
                        current_rich_text.extend(block[block_type]['rich_text'])
                    else:
                        blocks.append(block)
            elif node_type in ['strong', 'emphasis']:
                styled_elements = self.process_inlines(inline['children'], block_type=block_type)
                for block in styled_elements:
                    if block['type'] == block_type:
                        for rt in block[block_type]['rich_text']:
                            annotations = rt.get('annotations', {})
                            if node_type == 'strong':
                                annotations['bold'] = True
                            else:
                                annotations['italic'] = True
                            rt['annotations'] = annotations
                        current_rich_text.extend(block[block_type]['rich_text'])
                    else:
                        blocks.append(block)
            else:
                # Handle other inline types if necessary
                pass

        # Add any remaining text as a block
        if current_rich_text:
            blocks.append(self.create_text_block(block_type, current_rich_text))

        return blocks

    def create_text_rich_text(self, inline):
        return {
            "type": "text",
            "text": {
                "content": inline['text']
            }
        }

    def create_text_block(self, block_type, rich_text):
        return {
            "object": "block",
            "type": block_type,
            block_type: {
                "rich_text": rich_text
            }
        }

    def create_image_block(self, node):
        alt_text = node.get('alt', '')  # Extract alt text from the node
        image_block = {
            "object": "block",
            "type": "image",
            "image": {
                "type": "external",
                "external": {
                    "url": node['src']
                }
            }
        }

        if alt_text:
            # Add a caption to the image block
            image_block["image"]["caption"] = [{
                "type": "text",
                "text": {
                    "content": alt_text
                }
            }]

        return image_block

    def create_code_block(self, node):
        code = node['text']
        language = node.get('info') or 'plain text'
        return {
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": code
                    }
                }],
                "language": language
            }
        }

renderer = NotionRenderer()

class NotionBot():
    def __init__(self):
        self.client = Client(auth=os.environ["NOTION_TOKEN"])
        self.db_id = self.get_database_id()

        self._message_handler: MessageHandler = None

    def get_database_id(self):
        # get the database id
        results = self.client.search(query="").get("results")
        for result in results:
            if result["object"] == "database":
                return result["id"]

    def markdown_to_notion_blocks(self, markdown_text):
        markdown = mistune.create_markdown(renderer='ast')
        ast = markdown(markdown_text)
        blocks = self.process_nodes(ast)
        return blocks

    def create_page(self, title, content=""):
        # Convert markdown to Notion blocks
        blocks = renderer.render(content)

        # create a page and add it to the database
        properties = {
            "parent": { "database_id": self.db_id },
            "properties": {
                "title": {
                    "title": [{ "type": "text", "text": { "content": title } }]
                }
            },
            "children": blocks
        }

        page = self.client.pages.create(**properties)
        return page

    def update_block(self, block_id, content):
        """Update a specific block with new content"""
        # Render the content to get the appropriate block structure
        # get block type of the existing block
        block = self.client.blocks.retrieve(block_id=block_id)
        block_type = block['type']

        new_blocks = renderer.render(content)

        # Assuming the content is a single block, update the block
        if new_blocks:
            new_block = new_blocks[0]  # Get the first block from the rendered content
            new_block_type = new_block['type']

        # Update the block with the new content
        try:
            if block_type == new_block_type:
                self.client.blocks.update(
                    block_id=block_id,
                    **{block_type: block[block_type]}
                )
            else:
                # If the block type has changed, replace the block
                self.replace_block(block_id, block['parent']['id'], content)
        except Exception as e:
            print(f"Error updating block {block_id}: {str(e)}")

    def replace_block(self, block_id, parent_id, content):
        try:
            # Delete the existing block
            self.client.blocks.delete(block_id=block_id)

            # Create a new text block
            blocks = renderer.render(content)

            # Assuming you have the parent block or page ID where this block should be added
            parent_id = "your_parent_block_or_page_id"

            # Add the new block to the parent
            self.client.blocks.children.append(
                block_id=parent_id,
                children=blocks
            )
        except Exception as e:
            print(f"Error replacing block {block_id} with parent {parent_id}: {e}")

tool_specs = [
    {
        "type": "function",
        "function": {
            "name": "create_page",
            "description": "Create and upload a new Notion page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The title of the page."
                    },
                    "content": {
                        "type": "string",
                        "description": "The content of the page."
                    }
                },
                "required": ["title"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_block",
            "description": "Update a specific block in a Notion page. Use this to modify Notion pages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "block_id": {
                        "type": "string",
                        "description": "The ID of the block to update."
                    },
                    "content": {
                        "type": "string",
                        "description": "The new content of the block."
                    }
                },
                "required": ["block_id", "content"],
                "additionalProperties": False
            }
        }
    }
]

notion_bot = NotionBot()

tool_maps = {
    "create_page": notion_bot.create_page,
    "update_block": notion_bot.update_block
}

if __name__ == "__main__":
    title = "Test Page"
    content = "This is a test page created using the Notion API"
    markdown_content = """
![Product Categories Pie Chart](https://i.imgur.com/oLNji6e.png)
The analysis of the uploaded CSV file has been completed, and I've generated a pie chart showing the distribution of product categories. You can view the chart below:
![Product Categories Pie Chart](https://i.imgur.com/oLNji6e.png)
If you need any further analysis or have additional questions, feel free to let me know!
![Product Categories Pie Chart](https://i.imgur.com/oLNji6e.png)"""

    page = notion_bot.create_page(title, markdown_content)