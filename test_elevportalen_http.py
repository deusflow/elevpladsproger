import httpx
import re
resp = httpx.get("https://www.elevportalen.dk/ledige-elevpladser/?search=it")
content = resp.text
links = re.findall(r'<a[^>]+href="([^"]+/ledige-elevpladser/[^"]+)"[^>]*>(.*?)</a>', content, re.IGNORECASE | re.DOTALL)
print(f"Found {len(links)} links")
