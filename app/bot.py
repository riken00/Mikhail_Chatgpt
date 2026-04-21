import importlib.util
import json
import logging
import os
import random
import select
import sys
import time

import undetected_chromedriver as uc
from dotenv import load_dotenv
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .models import ParaphrasedText, Text, user_details

load_dotenv()

logger = logging.getLogger("bot")

# Max retries when waiting for the login page to show the login button.
LOGIN_PAGE_MAX_RETRIES = 10

# Default timeout (seconds) for waiting on an OTP code from stdin.
OTP_INPUT_TIMEOUT = 120

# Default max prompts per chat before rotating to a new conversation.
DEFAULT_MAX_PROMPTS_PER_CHAT = 50


def execute_code_from_file(file_path: str, **kwargs):
    spec = importlib.util.spec_from_file_location("module.name", file_path)
    module = importlib.util.module_from_spec(spec)
    for key, value in kwargs.items():
        module.__dict__[key] = value
    spec.loader.exec_module(module)


class Bot:

    CHATGPT_URL = "https://chatgpt.com/"

    def __init__(self, account: user_details | None = None):
        if account:
            self.email = account.email
            self.password = account.password
            self._profile_name = account.profile or "Default"
            self._profile_dict = account.ProfileDict or "Profiles"
        else:
            self.email = os.getenv("EMAIL", "")
            self.password = os.getenv("EMAIL_PASSWORD") or os.getenv("PASSWORD", "")
            self._profile_name = "Default"
            self._profile_dict = "Profiles"

        self.driver = None
        self.all_response_text: list[str] = []
        self._prompt_count = 0
        self.max_prompts_per_chat = DEFAULT_MAX_PROMPTS_PER_CHAT

    def get_driver(self, profile_name: str = "", profile_dict: str = "") -> None:
        """Spin up an undetected Chrome instance with the given profile."""
        profile_name = profile_name or self._profile_name
        profile_dict = profile_dict or self._profile_dict

        options = uc.ChromeOptions()
        options.add_argument(f"--user-data-dir={profile_dict}")
        options.add_argument(f"--profile-directory={profile_name}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--headless")
        

        self.driver = uc.Chrome(options=options, version_main=145)
        self.driver.maximize_window()
        logger.info("Chrome launched -- profile: %s/%s", profile_dict, profile_name)

    def CloseDriver(self):
        """Gracefully close the browser."""
        try:
            if self.driver:
                self.driver.quit()
                logger.info("Browser closed.")
        except Exception:
            pass
        finally:
            self.driver = None

    def find_element(self, label: str, locator: str,
                     locator_type=By.XPATH, timeout: int = 10):
        """Wait for an element and return it, or None on failure."""
        try:
            if timeout > 0:
                ele = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((locator_type, locator))
                )
            else:
                ele = self.driver.find_element(by=locator_type, value=locator)
            logger.debug("Found: %s", label)
            return ele
        except (NoSuchElementException, TimeoutException):
            logger.debug("Not found: %s", label)
            return None

    def click_element(self, label: str, locator: str,
                      locator_type=By.XPATH, timeout: int = 10):
        """Find an element and click it; return it or None."""
        ele = self.find_element(label, locator, locator_type, timeout=timeout)
        if ele:
            ele.click()
            logger.debug("Clicked: %s", label)
            return ele
        return None

    def input_text(self, text: str, label: str, locator: str,
                   locator_type=By.XPATH, timeout: int = 10):
        """Find an input, clear it, type text, and return the element or None."""
        ele = self.find_element(label, locator, locator_type, timeout=timeout)
        if ele:
            time.sleep(0.8)
            ele.clear()
            ele.send_keys(text)
            logger.debug("Typed into: %s", label)
            return ele
        return None

    def random_sleep(self, low: int = 5, high: int = 8) -> None:
        """Sleep a random number of seconds to mimic human pacing."""
        secs = random.randint(low, high)
        logger.debug("Sleeping %d s ...", secs)
        time.sleep(secs)

    def _is_logged_in(self) -> bool:
        self.driver.save_screenshot("debug_login_check.png")
        self.driver.refresh()
        self.random_sleep()
        script = self.find_element(
            "client-script", '//script[@id="client-bootstrap"]', timeout=5
        )
        if script:
            content = script.get_attribute("innerHTML")
            if content and '{"authStatus":"logged_in"' in content:
                logger.info("Already logged in as %s", self.email)
                return True
        return False

    def login_chat(self, close_driver: bool = True) -> bool:
        if not self.driver:
            self.get_driver()

        breakpoint()
        self.driver.get(self.CHATGPT_URL)
        if self._is_logged_in():
            if close_driver:
                self.CloseDriver()
            return True

        login_btn_xpath = '//button[@data-testid="login-button"]'
        for attempt in range(LOGIN_PAGE_MAX_RETRIES):
            self.driver.refresh()
            btn = self.find_element("Login button", login_btn_xpath, timeout=3)
            if btn and btn.text.strip().lower() == "log in":
                break
            if attempt > 0:
                # Brief exponential backoff
                time.sleep(min(2 ** attempt, 10))
        else:
            logger.error("Login button never appeared for %s", self.email)
            self.CloseDriver()
            return False

        self.click_element("Login btn", login_btn_xpath)
        self.random_sleep()

        if self.input_text(self.email, "Email input", '//*[@id="email"]'):
            self.click_element("Continue", '//button[@type="submit"]')
            self.random_sleep(5, 10)

        self.input_text(self.password, "Password input", '//input[@type="password"]')
        self.click_element("Continue", '//button[@type="submit"]')

        email_verification = self.find_element(
            "email verification", "//form[@action='/email-verification']"
        )
        if email_verification:
            if self.find_element("Verification code input", '//input[@name="code"]'):
                otp_code = self._read_otp_with_timeout()
                if otp_code:
                    self.input_text(
                        otp_code, "Verification code input", '//input[@name="code"]'
                    )
                    self.click_element("Verify", '//button[@type="submit"]')
                else:
                    logger.error(
                        "OTP input timed out after %d s for %s",
                        OTP_INPUT_TIMEOUT, self.email,
                    )
                    if close_driver:
                        self.CloseDriver()
                    return False

        if self._is_logged_in():
            logger.info("Logged in successfully: %s", self.email)
            if close_driver:
                self.CloseDriver()
            return True

        logger.error("Login failed for %s", self.email)
        if close_driver:
            self.CloseDriver()
        return False

    def _read_otp_with_timeout(self, timeout: int = OTP_INPUT_TIMEOUT) -> str | None:
        """
        Read an OTP code from stdin with a timeout.
        Returns None if the timeout expires without input.
        """
        prompt_msg = f"Enter the OTP sent to {self.email} (timeout {timeout}s): "
        print(prompt_msg, end="", flush=True)

        # On Linux/macOS we can use select() to wait with a timeout.
        # On Windows select() does not work on stdin, so fall back to plain input().
        if sys.platform == "win32":
            # No timeout support on Windows -- fall back to blocking input
            try:
                return input().strip() or None
            except EOFError:
                return None

        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            line = sys.stdin.readline().strip()
            return line or None
        return None

    def start_new_chat(self) -> None:
        """Navigate to the ChatGPT home page to start a fresh conversation."""
        logger.info(
            "Rotating to new chat after %d prompts.", self._prompt_count,
        )
        self.driver.get(self.CHATGPT_URL)
        self._prompt_count = 0
        self.random_sleep(2, 4)

    def send_prompt(self, prompt: str) -> None:
        # Auto-rotate to a new chat if the prompt limit has been reached
        if self._prompt_count >= self.max_prompts_per_chat:
            self.start_new_chat()

        text_area = self.find_element("Prompt textarea", '//div[@id="prompt-textarea"]')
        if not text_area:
            raise RuntimeError("ChatGPT prompt textarea not found -- is the page loaded?")

        self.driver.execute_script(
            """
            const el = arguments[0];
            const text = arguments[1];
            el.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            el.innerHTML = '<p>' + text + '</p>';
            el.dispatchEvent(new InputEvent('input', {bubbles: true, data: text}));
            """,
            text_area,
            prompt,
        )
        time.sleep(1)
        self.click_element("Send button", '//button[@data-testid="send-button"]')
        self._prompt_count += 1
        logger.info(
            "Prompt sent (%d chars, #%d in this chat)",
            len(prompt), self._prompt_count,
        )

    def send_prompt_and_get_response(
        self, prompt: str, timeout: int = 180,
    ) -> str:
        """
        Convenience method: send a prompt, wait for ChatGPT to finish,
        and return the extracted response text.
        """
        self.send_prompt(prompt)
        self.wait_for_response_complete()
        return self.extract_response()

    def wait_for_response_complete(self) -> None:
        logger.info("Waiting for ChatGPT response ...")
        def check_response_done():
            send_prompt_xpath = '//button[@aria-label="Send prompt"]'
            if self.find_element("Start Voice btn", send_prompt_xpath, timeout=10):
                logger.info("Start Voice detected -- assuming response is complete")
                return True
            
            start_voice_xpath = '//button[@aria-label="Start Voice"]'
            if self.find_element("Start Voice btn", start_voice_xpath, timeout=10):
                logger.info("Voice response detected -- assuming response is complete")
                return True
            
            return False
        self.random_sleep(3,5)

        if not check_response_done():

            for _ in range(10):
                streaming_response_btn = '//button[@aria-label="Stop streaming"]'
                if self.find_element("Streaming response btn", streaming_response_btn, timeout=5):
                    logger.info("Streaming response detected -- waiting for completion")
                    self.random_sleep(5, 10)
                    continue
                else:
                    break
        
        return check_response_done()

    def extract_response(self) -> str:
        sections = self.driver.find_elements(By.TAG_NAME, "section")
        if not sections:
            logger.warning("No <section> elements found -- response may be empty")
            return ""

        raw = sections[-1].text

        raw = raw.replace("ChatGPT said:\n", "").strip()

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and len(parsed) == 1:
                sole_val = next(iter(parsed.values()))
                if isinstance(sole_val, str):
                    return sole_val
            return json.dumps(parsed, indent=2)
        except (json.JSONDecodeError, ValueError):
            return raw

    def generate_company_description(self, company_text: str) -> str:
        truncated = company_text.strip()

        prompt = f"""You are a professional business writer and copywriter.

Using ONLY the information provided below, write a compelling company description of approximately 250 words.

Requirements:
- Write in third-person, professional yet engaging tone.
- Cover what the company does, its core products/services, mission, and value proposition.
- Sound like a human copywriter wrote it -- natural, confident, not robotic.
- Do NOT use filler phrases like "In conclusion", "The company strives", or "leverages cutting-edge".
- Do NOT add any information that is not in the source text.
- Output ONLY valid JSON in this exact format -- no markdown, no explanation, nothing else:
{{"description": "<your 250-word description here>"}}

Source information:
{truncated}
"""
        self.send_prompt(prompt)
        self.wait_for_response_complete()

        raw = self.extract_response()
        logger.info("Raw description response (%d chars)", len(raw))

        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "description" in data:
                return str(data["description"]).strip()
        except (json.JSONDecodeError, ValueError):
            pass

        return raw.strip()

    def pharaprase_text(self, Text: str = "", another: bool = False, response: int = 0) -> int:
        for _ in range(3):
            text_area = self.find_element(
                "Textarea",
                '/html/body/div/div/div[1]/main/div[2]/form/div/div[2]/textarea',
            )
            action = ActionChains(self.driver)
            action.move_to_element(text_area).click()

            par = f'paraphrase {random.randint(15, 20)} times the following sentence '
            content = (
                f'more {random.randint(15, 20)} times' if another
                else f'{par} "{Text}"'
            )
            for letter in content:
                action.send_keys(letter)
                action.pause(0.08)
                action.perform()

            self.click_element("Send", '//*[@id="__next"]/div/div[1]/main/div[2]/form/div/div[2]/button')
            self.click_element("Scroll", '//*[@id="__next"]/div/div[1]/main/div[1]/div/div/button', timeout=1)

            for _ in range(30):
                regen = self.find_element(
                    "Regenerate", '//*[@id="__next"]/div[1]/div[1]/main/div[2]/form/div/div[1]/button'
                )
                if regen and regen.text == "Regenerate response":
                    break
                time.sleep(random.randint(3, 9))

            all_chat = self.driver.find_elements(
                By.XPATH, '//*[@id="__next"]/div/div[1]/main/div[1]/div/div/div/*'
            )
            if not all_chat:
                return response
            latest = all_chat[-1].find_elements(By.XPATH, '//div/div[2]/div[1]/div/div/ol/*')
            return len(latest)
        return response

    def AddPraprasedSentenceIntoList(self) -> None:
        all_chat = self.driver.find_elements(
            By.XPATH, '//*[@id="__next"]/div/div[1]/main/div[1]/div/div/div/*'
        )
        if not all_chat:
            return
        latest = all_chat[-1].find_elements(By.XPATH, '//div/div[2]/div[1]/div/div/ol/*')
        for item in latest:
            self.all_response_text.append(item.text)

    def work(self) -> None:
        logged_in = self.login_chat(close_driver=False)
        if not logged_in:
            logger.error("Login failed -- aborting work()")
            return

        self.driver.get(self.CHATGPT_URL)
        self.random_sleep(3, 6)

        title = "New Way of Energy Dissipation in Graphene Nano-Resonators"
        desc = (
            "ICFO researchers Johannes Guttinger, Adrien Noury, Peter Weber, "
            "Camille Lagoin, Joel Moser, led by Prof. Adrian Bachtold, in partnership "
            "with researchers from Chalmers University of Technology and ETH Zurich, "
            "established an explanation of non-linear dissipation in graphene nano-resonators."
        )
        prompt = f"""You are a precise news entity extraction API.
Extract named entities (organizations, persons, locations, institutions, investors)
explicitly mentioned in the text below.
Rules: output strict valid JSON only -- no markdown, no explanation.
Schema: {{"entities": [{{"name": "string", "type": "string"}}]}}

Title: {title}
Description: {desc}"""

        self.send_prompt(prompt)
        self.wait_for_response_complete()
        result = self.extract_response()
        print("Response:\n", result)