import os

GITHUB_API_TOKEN = os.getenv('GITHUB_API_TOKEN')

if not GITHUB_API_TOKEN:
    raise ValueError('GITHUB_API_TOKEN is required to run the script')
