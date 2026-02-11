import urllib.request, json, yaml

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

api_base_url   = cfg["api_base_url"]
api_key   = cfg["api_key"]
print(f'Token {api_key}', f'https://{api_base_url}/server/api/submissions/?page=1&page_size=10')
req = urllib.request.Request(f'https://{api_base_url}/server/api/submissions/?page=1&page_size=10')
req.add_header(f'Authorization', 'Token {api_key}')
response = urllib.request.urlopen(req)
data = json.loads(response.read())
for submission in data['results']: #here we will create directories and views
  print("id: {}, project_id: {}".format(submission['id'], submission['internal_id'])) #test
