import requests

# 测试 okxcn.com 的 API 端点，添加 JSON 请求头
url = 'https://www.okxcn.com/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=3'
headers = {
    'Accept': 'application/json',
    'User-Agent': 'Mozilla/5.0',
}
print(f'Testing: {url}')
print(f'Headers: {headers}')
try:
    r = requests.get(url, headers=headers, timeout=10)
    print(f'Status: {r.status_code}')
    print(f'Content-Type: {r.headers.get("Content-Type", "")}')
    print(f'Body: {r.text[:500]}')
except Exception as e:
    print(f'Error: {e}')
