import re

with open('elevportalen.html', 'r') as f:
    content = f.read()

links = set(re.findall(r'<a[^>]+href="([^"]+/ledige-elevpladser/[^"]+)"[^>]*>(.*?)</a>', content, re.IGNORECASE | re.DOTALL))
for href, text in list(links)[:20]:
    clean_text = re.sub(r'<[^>]+>', '', text).strip()
    if clean_text:
        print(f"Title: {clean_text}, Link: {href}")
