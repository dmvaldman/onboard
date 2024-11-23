import json

from googleapiclient.discovery import build
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv('creds/.env')

def create_gsuite_user(email_admin, email_address, first_name, last_name):
    # Set up credentials and create the service
    SCOPES = ['https://www.googleapis.com/auth/admin.directory.user']
    SERVICE_ACCOUNT_FILE = 'creds/onboard_service_account.json'

    credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)

    # Delegate domain-wide authority to the service account
    delegated_credentials = credentials.with_subject(email_admin)

    service = build('admin', 'directory_v1', credentials=delegated_credentials)

    try:
        # Check if user exists
        try:
            existing_user = service.users().get(userKey=email_address).execute()
            print(f"User {email_address} already exists.")
            return existing_user
        except Exception as e:
            if "404" not in str(e):  # If error is not "user not found"
                raise e

        # User doesn't exist. Create them.
        password_temp = "password"
        user_data = {
            'primaryEmail': email_address,
            'name': {
                'givenName': first_name,
                'familyName': last_name
            },
            'password': password_temp,
            'changePasswordAtNextLogin': True
        }

        result = service.users().insert(body=user_data).execute()
        print(f"User {email_address} created successfully.")
        return result

    except Exception as e:
        print(f"An error occurred: {e}")
        return None

if __name__ == "__main__":
    # load json from agents/agent.json
    with open("agents/agent.json") as f:
        agent_data = json.load(f)

    email_user = agent_data['email']
    first_name = agent_data['first_name']
    last_name = agent_data['last_name']
    email_admin = os.environ.get('GSUITE_ADMIN_EMAIL')

    response = create_gsuite_user(email_admin, email_user, first_name, last_name)
    print(response)