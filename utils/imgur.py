import requests
import base64
import os

from dotenv import load_dotenv

load_dotenv('creds/.env', override=True)

def file_upload(image_bytes):
    # Imgur API endpoint
    url = "https://api.imgur.com/3/image"

    # Headers with your client ID
    headers = {
        'Authorization': f'Client-ID {os.environ.get("IMGUR_CLIENT_ID")}'
    }

    # Convert bytes to base64 if needed
    if isinstance(image_bytes, bytes):
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

    # Post the image
    response = requests.post(
        url,
        headers=headers,
        data={
            'image': image_b64,
            'type': 'base64'
        }
    )

    # Get the URL from response
    response_data = response.json()['data']

    return {
        'url': response_data['link'],
        'id': response_data['id']
    }