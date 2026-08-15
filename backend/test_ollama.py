import requests

url = "http://localhost:11434/api/generate"

payload = {
    "model": "qwen2.5:3b",
    "prompt": "Hello",
    "stream": False
}

response = requests.post(url, json=payload)

print("Status Code:", response.status_code)
print("Response:")
print(response.text)