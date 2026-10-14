import requests
import time

# 欧易 OKX 国内可能可用的域名批量测试
urls = [
    ('okx.cab', 'https://www.okx.cab/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=3'),
    ('ouyi.io', 'https://www.ouyi.io/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=3'),
    ('okxcn.com', 'https://www.okxcn.com/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=3'),
    ('okx-api.com', 'https://www.okx-api.com/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=3'),
    ('okx.me', 'https://www.okx.me/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=3'),
    ('okx.ink', 'https://www.okx.ink/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=3'),
    ('okx.wiki', 'https://www.okx.wiki/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=3'),
    ('ouyicn.com', 'https://www.ouyicn.com/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=3'),
    ('ouyiapi.com', 'https://www.ouyiapi.com/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=3'),
]

print(f'Testing {len(urls)} OKX domains...\n')

for name, url in urls:
    print(f'Testing {name}...', end=' ')
    start = time.time()
    try:
        r = requests.get(url, timeout=8)
        elapsed = time.time() - start
        if r.status_code == 200:
            print(f'SUCCESS! Status: {r.status_code}, Time: {elapsed:.2f}s')
            print(f'  Response: {r.text[:200]}')
        else:
            print(f'HTTP {r.status_code}, Time: {elapsed:.2f}s')
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        print(f'TIMEOUT ({elapsed:.1f}s)')
    except Exception as e:
        elapsed = time.time() - start
        err_msg = str(e)[:80]
        print(f'ERROR ({elapsed:.1f}s): {err_msg}')
