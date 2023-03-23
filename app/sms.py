
import requests,time, os
from urllib.parse import urlencode
from dotenv import load_dotenv
load_dotenv()

def get_number(pid='1331',country = 'my'):
    while True:
        url = "http://api.getsmscode.com/vndo.php?"

        payload = {
            "action": "getmobile",
            
            "username": "pay@noborders.net",
            "token": os.getenv('PASSWORD'),
            "pid": pid,
            "cocode":country
        }

        payload = urlencode(payload)
        full_url = url + payload
        response = requests.post(url=full_url)
        response = response.content.decode("utf-8")
        # print(response)
        # time.sleep(1000)
        if str(response) == 'Message|Capture Max mobile numbers,you max is 5':
            continue
        else:break
    return response

def get_sms(phone_number, pid='1331',country = 'my'):
    url = "http://api.getsmscode.com/vndo.php?"
    payload = {
        "action": "getsms",
        "username": "pay@noborders.net",
        "token": os.getenv('PASSWORD'),
        "pid": pid,
        "mobile": phone_number,
        "author": "pay@noborders.net",
        "cocode":country
    }
    payload = urlencode(payload)
    full_url = url + payload
    for x in range(10):
        response = requests.post(url=full_url).text
        print(response)
        if 'openai' in (response).lower():
            otp = response.strip().split(' ')[-1]
            return otp
        time.sleep(4)
        print(response)
    return False

def ban_number(phone_number, pid='1331',country = 'my'):
    url = "http://api.getsmscode.com/vndo.php?"
    payload = {
        "action": "addblack",
        "username": "pay@noborders.net",
        "token": os.getenv('PASSWORD'),
        "pid": pid,
        "mobile": phone_number,
        "author": "pay@noborders.net",
        "cocode":country
    }
    payload = urlencode(payload)
    full_url = url + payload
    response = requests.post(url=full_url)
    print(response.text)
    return response

