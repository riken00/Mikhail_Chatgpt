import json
import logging
import os
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

# Set up logging for the script
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fetch_chatgpt_network():
    """
    Spins up a Chrome instance, sends a prompt to ChatGPT, 
    and extracts the network logs for the conversation API.
    """
    
    # Configure performance logging to capture network requests
    options = uc.ChromeOptions()
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    # Use an existing profile if possible (adjust path as needed)
    # options.add_argument("--user-data-dir=Profiles")
    # options.add_argument("--profile-directory=Profile_1")
    
    logger.info("Launching Chrome with performance logging...")
    driver = uc.Chrome(options=options)
    
    try:
        driver.get("https://chatgpt.com/")
        logger.info("Opened ChatGPT. Please ensure you are logged in.")
        
        # Wait for the prompt textarea to be present
        time.sleep(10) # Give some time for initial load/login
        
        prompt = "Hello, this is a network capture test. Please respond with 'Network captured!'"
        logger.info(f"Sending prompt: {prompt}")
        
        # Find textarea and send prompt
        # We use the same selector as in bot.py
        try:
            text_area = driver.find_element(By.XPATH, '//div[@id="prompt-textarea"]')
            # Focus and type
            text_area.send_keys(prompt)
            time.sleep(1)
            # Click send
            send_btn = driver.find_element(By.XPATH, '//button[@data-testid="send-button"]')
            send_btn.click()
        except Exception as e:
            logger.error(f"Failed to send prompt: {e}")
            return

        logger.info("Prompt sent. Waiting for response and capturing network logs...")
        time.sleep(10) # Wait for the stream to progress

        # Fetch performance logs
        logs = driver.get_log("performance")
        
        logger.info(f"Captured {len(logs)} performance events.")
        
        found_conversation = False
        for entry in logs:
            log_data = json.loads(entry["message"])["message"]
            
            # Look for Network.requestWillBeSent or Network.responseReceived
            method = log_data.get("method")
            params = log_data.get("params", {})
            
            if method == "Network.requestWillBeSent":
                request = params.get("request", {})
                url = request.get("url", "")
                
                # ChatGPT's main conversation API endpoint
                if "backend-api/conversation" in url:
                    found_conversation = True
                    logger.info("Found ChatGPT Conversation Request!")
                    print("\n--- [DANGER: Request Caught] ---")
                    print(f"URL: {url}")
                    print(f"Method: {request.get('method')}")
                    print(f"Headers: {json.dumps(request.get('headers'), indent=2)}")
                    if request.get("postData"):
                        print(f"Post Data: {request.get('postData')}")
                    print("---------------------------------\n")

            if method == "Network.responseReceived":
                response = params.get("response", {})
                url = response.get("url", "")
                
                if "backend-api/conversation" in url:
                    logger.info("Found ChatGPT Conversation Response!")
                    print("\n--- [DANGER: Response Headers Caught] ---")
                    print(f"URL: {url}")
                    print(f"Status: {response.get('status')}")
                    print(f"MimeType: {response.get('mimeType')}")
                    print(f"Headers: {json.dumps(response.get('headers'), indent=2)}")
                    print("------------------------------------------\n")

        if not found_conversation:
            logger.warning("Could not find the conversation API call in the captured logs.")
            logger.info("Try increasing the wait time or checking if the API endpoint has changed.")

    finally:
        logger.info("Closing browser in 10 seconds... (Check the console for output)")
        time.sleep(10)
        driver.quit()

if __name__ == "__main__":
    fetch_chatgpt_network()
