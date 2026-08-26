import requests
import base64
import json
import glob
import os
import getpass

# =========================================================
# CONFIGURATION
# =========================================================
CONFLUENCE_URL = "https://confluence.ecmwf.int"
USERNAME = getpass.getuser()
SPACE_KEY = f"~{USERNAME}"
PAGE_TITLE = "How to create automated confluence pages in python?"
API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")
if not API_TOKEN:
    raise ValueError("API token not found. Please set the CONFLUENCE_API_TOKEN environment variable.") 

# Folder where the figures are saved
FIGURE_FOLDER = "/home/ecm2892/repos/test_folder/generate_confluence_page/"

# =========================================================
# FIND FIGURES 
# =========================================================
pattern = os.path.join(FIGURE_FOLDER, "glofas_*20251015_event_1_24h.png")
image_files = sorted(glob.glob(pattern))

if not image_files:
    print("WARNING: No images found for pattern:", pattern)
else:
    print(f"Found {len(image_files)} images to attach:")
    for img in image_files:
        print(f"  - {img}")

# =========================================================
# CREATE BASE PAGE (FIXED FOR ECMWF CONFLUENCE)
# =========================================================
headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json; charset=utf-8"
}

create_page_url = f"{CONFLUENCE_URL}/rest/api/content"

data = {
    "type": "page",
    "title": PAGE_TITLE,
    "space": {"key": SPACE_KEY},
    "body": {
        "storage": {
            "value": "<p>Placeholder page content.</p>",
            "representation": "storage"
        }
    }
}

r = requests.post(create_page_url, headers=headers, json=data)

if not r.ok:
    print("ERROR: Failed to create page")
    print("Status:", r.status_code)
    print("Response:", r.text)
    r.raise_for_status()

page = r.json()
page_id = page["id"]
print(f"PAGE CREATED: {CONFLUENCE_URL}{page['_links']['webui']}")

# =========================================================
# UPLOAD FIGURES AS ATTACHMENTS
# =========================================================
def upload_attachment(page_id, file_path):
    filename = os.path.basename(file_path)
    attach_url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}/child/attachment"
    attach_headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Atlassian-Token": "no-check"  # fixes XSRF issue
    }
    files = {'file': (filename, open(file_path, 'rb'), 'image/png')}
    response = requests.post(attach_url, headers=attach_headers, files=files)
    if response.status_code in [200, 201]:
        print(f"UPLOADED: {filename}")
    else:
        print(f"ERROR: Failed to upload {filename}: {response.status_code} {response.text}")

if image_files:
    for img in image_files:
        upload_attachment(page_id, img)
else:
    print("INFO: Skipping image upload — no images found.")

# =========================================================
# UPDATE PAGE CONTENT WITH EMBEDDED IMAGES
# =========================================================
get_url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}?expand=version"
resp = requests.get(get_url, headers=headers)
resp.raise_for_status()
current_version = resp.json()["version"]["number"]
new_version = current_version + 1
print(f"Updating page to version {new_version}")

expandable_text1 = """
<ac:structured-macro ac:name="expand">
  <ac:parameter ac:name="title">How to Create and Use Your Personal Confluence API Token</ac:parameter>
  <ac:rich-text-body>

<h3>How to create a Confluence API token (Personal Access Token)</h3>
<ol>
  <li><strong>Log in</strong> to <a href="https://confluence.ecmwf.int" target="_blank" rel="noopener">ECMWF Confluence</a>.</li>
  <li>Click your <strong>profile icon</strong> in the top-right corner.</li>
  <li>Choose <strong>Settings</strong> → <strong>Personal Access Tokens</strong>.</li>
  <li>Click <strong>Create token</strong>.</li>
  <li>Enter a short name (e.g. <strong>Python page generator</strong>) and, if asked, set an expiry date.</li>
  <li>Tick <strong>Write content (create / update pages)</strong> so the script can publish pages.</li>
  <li>Click <strong>Create</strong>.</li>
  <li><strong>Copy</strong> the generated token and store it safely — it will be shown <strong>only once</strong>.</li>
</ol>

<ac:structured-macro ac:name="note">
  <ac:rich-text-body>
    <p>
      Treat your API token like a password. Do not share it publicly or commit it to version control. 
      You can revoke or regenerate your token at any time from <em>Personal Access Tokens</em> in your Confluence profile settings.
    </p>
  </ac:rich-text-body>
</ac:structured-macro>

<h3>Storing the API Token Securely</h3>
<p>
  Instead of hardcoding the token directly in your script, you can store it as an environment variable in your 
  <code>~/.bashrc</code> file. This allows Python to read it automatically each time you run the script.
</p>

<h4>1. Add the token to your <code>~/.bashrc</code> file</h4>
<pre><code>export CONFLUENCE_API_TOKEN="paste_your_token_here"
</code></pre>
<p>
  Then reload your configuration so it becomes active:
</p>
<pre><code>source ~/.bashrc
</code></pre>
<p>
  The token will now be available in all future terminal sessions.
</p>

<h4>2. Access the token inside your Python script</h4>
<p>
  In your script, import the <code>os</code> module and read the token from the environment variable:
</p>
<pre><code>import os

API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")

if not API_TOKEN:
    raise ValueError("API token not found. Please set the CONFLUENCE_API_TOKEN environment variable.")
</code></pre>

<h4>3. Run your script normally</h4>
<pre><code>python3 generate_confluence_page.py
</code></pre>

  </ac:rich-text-body>
</ac:structured-macro>
"""

expandable_text2 = """
<ac:structured-macro ac:name="expand">
  <ac:parameter ac:name="title">Click to see details</ac:parameter>
  <ac:rich-text-body>
    <p>This section can be expanded or collapsed. It could contain more plots or more text. Note that ChatGPT is very good at helping with HTML formatting!</p>
  </ac:rich-text-body>
</ac:structured-macro>
"""

if image_files:
    image_blocks = "\n".join(
        f'<h3>{os.path.basename(img)}</h3>\n<ac:image><ri:attachment ri:filename="{os.path.basename(img)}" /></ac:image>'
        for img in image_files
    )
else:
    image_blocks = "<p><em>No images available for this run.</em></p>"

page_content = f"""
<h1>This is an example confluence page</h1>
<p>This page illustrates an example of a Confluence page generated automatically from Python. 
The code to generate this page can be found here: <strong>{os.path.join(FIGURE_FOLDER, 'generate_confluence_page.py')}</strong></p>

<h2>Creating Your Personal Confluence API Token</h2>
<p>
  You will need your own personal Confluence API token to create automated pages. 
  Click below to follow the steps to generate a Personal Access Token.
</p>

{expandable_text1}

<h2>Aim: TEST</h2>
<h2>Date: 20251015</h2>

{image_blocks}

<h2>Additional Information</h2>
{expandable_text2}
"""

update_url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}"
update_payload = {
    "id": page_id,
    "type": "page",
    "title": PAGE_TITLE,
    "version": {"number": new_version},
    "body": {
        "storage": {
            "value": page_content,
            "representation": "storage"
        }
    }
}

update_headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

r = requests.put(update_url, headers=update_headers, data=json.dumps(update_payload))
r.raise_for_status()

print("PAGE CONTENT UPDATED SUCCESSFULLY.")
print(f"VIEW PAGE: {CONFLUENCE_URL}{page['_links']['webui']}")

