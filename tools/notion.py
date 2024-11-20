import dotenv
import os

import mistune
from notion_client import Client


dotenv.load_dotenv('creds/.env')

notion = Client(auth=os.environ["NOTION_TOKEN"])

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
        return {
            "object": "block",
            "type": "image",
            "image": {
                "type": "external",
                "external": {
                    "url": node['src']
                }
            }
        }

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

def get_database_id():
    # get the database id
    results = notion.search(query="").get("results")
    for result in results:
        if result["object"] == "database":
            return result["id"]

def markdown_to_notion_blocks(markdown_text):
    markdown = mistune.create_markdown(renderer='ast')
    ast = markdown(markdown_text)
    blocks = process_nodes(ast)
    return blocks

def create_page(title, content=""):
    # Convert markdown to Notion blocks
    blocks = renderer.render(content)

    db_id = get_database_id()

    # create a page and add it to the database
    properties = {
        "parent": { "database_id": db_id },
        "properties": {
            "title": {
                "title": [{ "type": "text", "text": { "content": title } }]
            }
        },
        "children": blocks
    }

    page = notion.pages.create(**properties)
    return page

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
    }
]

tool_maps = {
    "create_page": create_page
}

if __name__ == "__main__":
    title = "Test Page"
    content = "This is a test page created using the Notion API"
    markdown_content = """![Product Categories Pie Chart](https://i.imgur.com/oLNji6e.png)
    The analysis of the uploaded CSV file has been completed, and I've generated a pie chart showing the distribution of product categories. You can view the chart below:
![Product Categories Pie Chart](https://i.imgur.com/oLNji6e.png)
If you need any further analysis or have additional questions, feel free to let me know!
![Product Categories Pie Chart](https://i.imgur.com/oLNji6e.png)"""

    page = create_page(title, markdown_content)