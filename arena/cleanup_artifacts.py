"""After successful publication, delete only obsolete Pages deployment copies."""
import json
import os
import urllib.request

repo=os.environ["GITHUB_REPOSITORY"]; current=int(os.environ["GITHUB_RUN_ID"])
base=f"https://api.github.com/repos/{repo}/actions/artifacts"
headers={"Authorization":"Bearer "+os.environ["GH_TOKEN"],"Accept":"application/vnd.github+json","User-Agent":"OSL-artifact-maintenance"}
obsolete=[]; page=1
while True:
    with urllib.request.urlopen(urllib.request.Request(base+f"?per_page=100&page={page}",headers=headers),timeout=20) as response: items=json.load(response)["artifacts"]
    obsolete.extend(int(a["id"]) for a in items if a["name"]=="github-pages" and a.get("workflow_run",{}).get("id")!=current)
    if len(items)<100:break
    page+=1
for identity in obsolete:
    with urllib.request.urlopen(urllib.request.Request(base+"/"+str(identity),headers=headers,method="DELETE"),timeout=20) as response:response.read()
print(f"Removed {len(obsolete)} obsolete Pages artifacts; current broadcast and test evidence retained.")
