# import requests
# import pandas as pd


# url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"

# response = requests.get(url, timeout=10)

# print("HTTP 狀態碼：", response.status_code)

# data = response.json()

# print("取得資料筆數：", len(data))

# df = pd.DataFrame(data)

# print("\n資料欄位：")
# print(df.columns.tolist())

# print("\n前 5 筆資料：")
# print(df.head())

import requests
import pandas as pd


url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"

response = requests.get(
    url,
    timeout=10
)

response.raise_for_status()

data = response.json()

df = pd.DataFrame(data)

print("資料筆數：", len(df))

print("\n資料欄位：")
print(df.columns.tolist())


# 找出 2330 台積電
stock = df[df["Code"] == "2330"]

print("\n2330 台積電資料：")

if stock.empty:
    print("找不到 2330")
else:
    print(stock.to_string(index=False))
#目前沒用到