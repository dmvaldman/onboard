from notion_client import Client
import dotenv
import os

dotenv.load_dotenv('creds/.env')

notion = Client(auth=os.environ["NOTION_TOKEN"])

def get_database_id():
    # get the database id
    results = notion.search(query="").get("results")
    for result in results:
        if result["object"] == "database":
            return result["id"]

def create_page(title, content=""):
    db_id = get_database_id()

    # create a page and add it to the database
    properties = {
        "parent": {
            "database_id": db_id
        },
        "properties": {
            "title": {
                "title": [{ "type": "text", "text": { "content": title } }]
            }
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{ "type": "text", "text": { "content": content } }]
                }
            }
        ]
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

    db_id = get_database_id()
    page = create_page(db_id, title, content)