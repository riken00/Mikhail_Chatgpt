from logging import exception
import profile
from xml.dom import UserDataHandler
from django.core.management.base import BaseCommand
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException,InvalidElementStateException
import time, random, pandas as pd
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
import  json, os
from faker import Faker
from urllib3 import Retry
from .models import Text as TxtObj, ParaphrasedText, user_details
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
import undetected_chromedriver as uc
from dotenv import load_dotenv
from .sms import get_number,get_sms,ban_number
load_dotenv()



import importlib.util
def execute_code_from_file(file_path, **kwargs):
    # Load the code from the file
    spec = importlib.util.spec_from_file_location("module.name", file_path)
    module = importlib.util.module_from_spec(spec)
    # Pass the keyword arguments to the module
    for key, value in kwargs.items():
        module.__dict__[key] = value
    spec.loader.exec_module(module)

class Bot:
    def __init__(self):
        self.all_response_text = []
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('EMAIL_PASSWORD')
        
    def get_driver(self,profile_name='Default',profileDict = 'Profiles') :
        options = uc.ChromeOptions()

        options.add_argument(f"--user-data-dir={profileDict}")
        options.add_argument(f'--profile-directory={profile_name}')
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        self.driver = uc.Chrome(
            options=options,
            version_main=145   # 🔥 MATCH YOUR CHROME VERSION
        )

        self.driver.maximize_window()
        
    def find_element(self, element, locator, locator_type=By.XPATH,
            page=None, timeout=10,
            condition_func=EC.presence_of_element_located,
            condition_other_args=tuple()):
        """Find an element, then return it or None.
        If timeout is less than or requal zero, then just find.
        If it is more than zero, then wait for the element present.
        """
        try:
            if timeout > 0:
                wait_obj = WebDriverWait(self.driver, timeout)
                ele = wait_obj.until(
                         EC.presence_of_element_located(
                             (locator_type, locator)))
                # ele = wait_obj.until(
                #         condition_func((locator_type, locator),
                #             *condition_other_args))
            else:
                print(f'Timeout is less or equal zero: {timeout}')
                ele = self.driver.find_element(by=locator_type,
                        value=locator)
            if page:
                print(
                        f'Found the element "{element}" in the page "{page}"')
            else:
                print(f'Found the element: {element}')
            return ele
        except (NoSuchElementException, TimeoutException) as e:
            if page:
                print(f'Cannot find the element "{element}"'
                        f' in the page "{page}"')
            else:
                print(f'Cannot find the element: {element}')
                
    def click_element(self, element, locator, locator_type=By.XPATH,
            timeout=10):
        """Find an element, then click and return it, or return None"""
        ele = self.find_element(element, locator, locator_type, timeout=timeout)
        if ele:
            ele.click()
            print(f'Clicked the element: {element}')
            return ele

    def input_text(self, text, element, locator, locator_type=By.XPATH,
            timeout=10, hide_keyboard=True):
        """Find an element, then input text and return it, or return None"""
        
        ele = self.find_element(element, locator, locator_type=locator_type,
                timeout=timeout)
        if ele:
            time.sleep(1)
            ele.clear()
            ele.send_keys(text)
            print(f'Inputed "{text}" for the element: {element}')
            return ele    
    
    def change_window(self,index=0):
        AllWindow = self.driver.window_handles
        if index:
            self.driver.switch_to.window(AllWindow[index])
            return
            
        CurrentWindow = self.driver.current_window_handle
        for window in AllWindow:
            if window != CurrentWindow:
                self.driver.switch_to.window(window)
                break
        
    def login_gmail(self):
        ele = self.find_element('Input Field','//*[@id="identifierId"]')
        if ele:
            self.input_text(os.getenv('EMAIL'),'Input Field','//*[@id="identifierId"]')
            self.click_element('Next btn','//*[@id="identifierNext"]/div/button')
        self.random_sleep()
        
        ele2 = self.find_element('password Field','//*[@id="password"]/div[1]/div/div[1]/input')
        if ele2:
            self.input_text(os.getenv('PASSWORD'),'Input Field','//*[@id="password"]/div[1]/div/div[1]/input')
            self.click_element('Next btn','//*[@id="passwordNext"]/div/button')
        self.random_sleep()
        
    def verify_email(self):
        for _ in range(5):
            
            verify_enail = self.find_element('Verify email','//*[@id="root"]/div[1]/div/div[2]/h1')
            if verify_enail:
                if verify_enail.text == "Verify your email":break
                
        self.click_element('Open Gmail','//*[@id="root"]/div[1]/div/div[2]/a')
        self.change_window(-1)
        self.driver.get('https://mail.google.com/mail/u/0/#all')
        
        self.random_sleep(10,15)
        for i in range(1,6):
            email = self.find_element(f'Check email : {i}',f'/html/body/div[7]/div[3]/div/div[2]/div[2]/div/div/div/div/div[2]/div/div[1]/div/div/div[8]/div/div[1]/div[2]/div/table/tbody/tr[{i}]/td[4]/div[2]/span/span',timeout=3)
            if email:
                if email.get_attribute('email') == "noreply@tm.openai.com":
                    email.click()
                    break
        else :self.click_element('First email','/html/body/div[7]/div[3]/div/div[2]/div[2]/div/div/div/div/div[2]/div/div[1]/div/div[2]/div[4]/div[1]/div/table/tbody/tr[1]')

        verify_link = ''
        try:
            for link in self.driver.find_elements(By.TAG_NAME,'a'):
                try:
                    if link.get_attribute('data-saferedirecturl'):
                        if "verify email address" in link.text.lower():
                            verify_link = link.get_attribute('href')
                except : ...
                            
                if verify_link : break
        except Exception as e:print(e)
        self.click_element('delete email','/html/body/div[7]/div[3]/div/div[2]/div[2]/div/div/div/div/div[1]/div/div[1]/div/div[2]/div[3]')
        self.driver.get(verify_link)
        
    def random_sleep(self,x1=5,x2=8):
        rr = random.randint(x1,x2)
        print(f'time sleep : {rr}')
        time.sleep(rr)

    def get_new_password(self,length=random.randint(8,12)):
        import string,random
        self.password = ''.join(random.choices(string.ascii_letters + string.digits + string.punctuation, k=length))
        return self.password

    def get_ready_number_page(self):
        
        for _ in range(3):
            very_numberH1 = self.find_element('verify number h1','/html/body/div[1]/div[1]/div/div[2]/h1')
            if very_numberH1:
                if very_numberH1.text == "Verify your phone number":
                    break
                
        self.click_element('No whatsapp','//*[@id="whatsapp-opt-in"]/label[2]')
        self.click_element('Country drop down','//*[@id="root"]/div[1]/div/div[2]/form/div[1]/div/div[1]/div/div[2]/div')
        
        for _ in range(3):
            time.sleep(3)
            aa = self.find_element('dd','css-1de7owd-menu',By.CLASS_NAME,timeout=7)
            if aa : 
                aa = aa.find_elements(By.XPATH,'//*')
                break
        try:
            
            for i in aa:
                ele_text = i.text
                if not ele_text: continue
                try: 
                    if 'Malaysia' == i.text :
                        i.click()
                        break
                except Exception as e: print(e,'-1111')
        except Exception as e: print(e,'-2222')

    def login_chat(self,profile_name='', close_driver=True):
        def _check_login():
            self.random_sleep()

            client_script = self.find_element('clinet script','//script[@id="client-bootstrap"]',timeout=5)
            if client_script:
                client_script = client_script.get_attribute('innerHTML')
                if '{"authStatus":"logged_in"' in client_script:
                    print('Account already exists')
                    return True
            return False
        
        self.get_driver(profile_name )
        self.driver.get('https://chat.openai.com/chat')

        if _check_login(): 
            if close_driver:
                self.CloseDriver()
            return True

        LogOutbtn = self.click_element('log out','/html/body/div[1]/div[1]/div[2]/div/div/nav/a[5]')
        if LogOutbtn:self.random_sleep()
        login_btn_cpath = '//button[@data-testid="login-button"]'
        for _ in range(50):
            self.driver.refresh()
            welcome_ele = self.find_element('Welcome',login_btn_cpath,timeout=2)
            if welcome_ele:
                if welcome_ele.text == 'Log in': break
            
        else:
            self.CloseDriver()
            return False
        
        self.click_element('login btn',login_btn_cpath)
        self.random_sleep()

        if self.input_text(self.email,'Email input','//*[@id="email"]') :
            self.click_element('Continue','//button[@type="submit"]')
            self.random_sleep(5,10)
            pass

        self.input_text(self.password,'password input','//input[@type="password"]')
        self.click_element('Continue','//button[@type="submit"]')

        if _check_login(): 
            if close_driver:
                self.CloseDriver()
            return True
        
        return False
        
    def sign_in(self,UserEmail,UserPassword):
        self.click_element('Login btn','//*[@id="__next"]/div[1]/div/div[4]/button[1]')
        self.input_text(UserEmail,'Username input','//*[@id="username"]')
        self.click_element('Continue','/html/body/main/section/div/div/div/form/div[2]/button')
        self.input_text(UserPassword,'password input','//*[@id="password"]')
        self.click_element('Continue','/html/body/main/section/div/div/div/form/div[2]/button')

    def pharaprase_text(self,number=50,Text='',another=False,add_into_list=False, response=0,pharaprase=True):
        for i in range(3):
            textArea = self.find_element('text area','/html/body/div/div/div[1]/main/div[2]/form/div/div[2]/textarea') # /html/body/div/div/div[1]/main/div[2]/form/div/div[2]/textarea
            action = ActionChains(self.driver)
            action.move_to_element(textArea)
            action.click()
            par = f'paraphrase {random.randint(15,20)} times the following sentence ' if not another else f''
            Text = f'more {random.randint(15,20)} times' if another else f'{par} "{Text}"'
            for letter in Text:
                action.send_keys(letter)
                action.pause(0.1)
                action.perform()
            self.click_element('send btn','//*[@id="__next"]/div/div[1]/main/div[2]/form/div/div[2]/button')
            self.click_element('scroll down','//*[@id="__next"]/div/div[1]/main/div[1]/div/div/button',timeout=1)
            
            all_chat = self.driver.find_elements(By.XPATH,'//*[@id="__next"]/div/div[1]/main/div[1]/div/div/div/*')
            last_ele = all_chat.pop()
            self.not_found_bool = False
            for _ in range(30):
                                
                try:
                    RegenrateResponse = self.find_element('ReGenrate Response','//*[@id="__next"]/div[1]/div[1]/main/div[2]/form/div/div[1]/button')
                    if RegenrateResponse:
                        if RegenrateResponse.text == 'Regenerate response' :
                            break
                        else:
                            time.sleep(random.randint(3,9))
                            
                except Exception as e :
                    print(e)
                    
                First_text = all_chat[-1].find_elements(By.XPATH,'//div/div[2]/div[1]/div/div/ol/*')[0]
                if First_text.text.startswith("I'm sorry") or First_text.text.startswith("I apologize") :
                    break
            response = 0
            
            all_chat = self.driver.find_elements(By.XPATH,'//*[@id="__next"]/div/div[1]/main/div[1]/div/div/div/*')
            last_ele = all_chat.pop()
            latest_responses = all_chat[-1].find_elements(By.XPATH,'//div/div[2]/div[1]/div/div/ol/*')
            for __ in latest_responses:
                response+=1
            return response
             
    def AddPraprasedSentenceIntoList(self):
        all_chat = self.driver.find_elements(By.XPATH,'//*[@id="__next"]/div/div[1]/main/div[1]/div/div/div/*')
        last_ele = all_chat.pop()
        latest_responses = all_chat[-1].find_elements(By.XPATH,'//div/div[2]/div[1]/div/div/ol/*')
        for response in latest_responses:
            self.all_response_text.append(response.text)

    # def work(self,UserEmail,UserPassword):
        
    #     self.driver.get('https://chat.openai.com/chat')
    #     while True:
    #         time.sleep(3)
    #         capacity = self.find_element('High capacity','//*[@id="__next"]/div[1]/div/div/div[1]/div[1]',timeout=2)
    #         if capacity:
    #             if 'capacity' in capacity.text.lower():
    #                 self.driver.refresh()
    #                 continue
    #         break                

    #     login_btn = self.find_element('Login btn','//*[@id="__next"]/div[1]/div/div[4]/button[1]',timeout=2)
    #     if login_btn:
    #         if login_btn.text == 'Log in':
    #             self.sign_in(UserEmail,UserPassword)
    #             self.click_element('Next pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button',timeout=2)
    #             self.click_element('Next2 pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button[2]',timeout=2)
    #             self.click_element('Done pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button[2]',timeout=2)
        
    #     session_expired = self.find_element('Login expires','//*[@id="headlessui-dialog-title-:r2:"]')
    #     if session_expired :
    #         if session_expired.text == 'Your session has expired':
    #             self.click_element('Login','/html/body/div[3]/div/div/div/div[2]/div/div/div[2]/button')
    #             self.sign_in(UserEmail,UserPassword)
    #             self.click_element('Next pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button',timeout=2)
    #             self.click_element('Next2 pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button[2]',timeout=2)
    #             self.click_element('Done pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button[2]',timeout=2)
                
        
    #     time.sleep(random.randint(5,10))

    #     verify_one = self.find_element('Captcha','//*[@id="cf-stage"]/div[6]/label',timeout=2)
    #     if verify_one:
    #         if str(verify_one.text).upper() == "Verify you are human".upper():
    #             self.click_element('Verify box','//*[@id="cf-stage"]/div[6]/label/span',timeout=3)

    #     verify_two = self.click_element('Verify2','//*[@id="challenge-stage"]/div/input',timeout=2)
    #     if verify_two:
    #         if str(verify_two.text).upper() == "Verify you are human".upper():
    #             verify_two.click()
            
        
    #     sounds_good = self.find_element('Sounds good','//*[@id="headlessui-dialog-panel-:r1:"]/div[3]/button',timeout=3)
    #     if sounds_good:
    #         if sounds_good.text.upper() == "Sounds good!".upper():
    #             sounds_good.click()
                
    #     count_sentence = 0
    #     for _ in range(random.randint(10,20)):
    #         self.all_response_text = []
    #         count_sentence+=1
    #         text = TxtObj.objects.filter(pharaphreased="NOT_DONE").first() 
    #         text.pharaphreased = "RUNNING"
    #         text.save()
    #         time.sleep(random.randint(5,10))
    #         Text = text.text
    #         print(Text)
            
    #         response = 0
    #         self.pharaprase_text(Text=Text,response=response)
    #         for i in range(6):
    #             response = self.pharaprase_text(number=random.randint(10,15),Text=Text,another=True,response=response)
    #             if response > 50: break
            
    #         print('response',response)
    #         self.AddPraprasedSentenceIntoList()
                

    #         if self.not_found_bool == False:
    #             number_count = 1
                

    #             PageTitle = self.driver.title
    #             for response in self.all_response_text :
    #                 print(number_count,response)
    #                 ParaphrasedText.objects.create(
    #                     sentence = text,
    #                     response = response,
    #                     PageTitle = PageTitle,
    #                     number = number_count 
    #                 )
    #                 number_count += 1
                    
    #             text.pharaphreased = "DONE"
    #             text.save()
            
    #         self.click_element('Clear conversation','//*[@id="__next"]/div[1]/div[2]/div/div/nav/a[2]')
    #         time.sleep(2)
    #         self.click_element('Confirm clear conversation','//*[@id="__next"]/div[1]/div[2]/div/div/nav/a[2]')
    #         self.driver.refresh()
    #         # self.CloseDriver()
    #         # self.get_driver()
    #         # self.driver.get('https://chat.openai.com/chat')
    #     self.CloseDriver()

    def work(self):
        self.login_chat(close_driver=False)
        breakpoint()
        self.driver.get('https://chatgpt.com/')
        
        title = "New Way of Energy Dissipation in Graphene Nano-Resonators"
        desc = """This is a schematic cross-section of a graphene drum. (CREDIT- ICFO) 
                Energy dissipation is a key element in understanding numerous physical phenomena in thermodynamics, nuclear fission, photonics, photon emissions, chemical reactions, or even electronic circuits, among others. 
                The energy dissipation in a vibrating system is quantified by the quality factor. If the quality factor of the resonator is high, the mechanical energy will dissipate at an extremely very low rate, and accordingly the resonator will be very accurate at sensing or measuring objects thus enabling these systems to become exciting quantum systems, as well as highly sensitive mass and force sensors. For instance, when a guitar string is made to vibrate, the vibration produced in the string resonates in the body of the guitar. Since the vibrations of the body are robustly coupled to the surrounding air, the energy of the string vibration will dissipate more efficiently into the environment bath, raising the volume of the sound. The decay is established to be linear, as it does not rely on the vibrational amplitude. 
                Now, shrink the guitar string down to nano-meter dimensions to attain a nano-mechanical resonator. In these nano systems, energy dissipation has been perceived to depend on the amplitude of the vibration, defined as a non-linear phenomenon, and up to now no proposed theory has been demonstrated to properly describe this dissipation process. 
                In a recent research, published in Nature Nanotechnology , ICFO researchers Johannes Güttinger, Adrien Noury, Peter Weber, Camille Lagoin, Joel Moser, led by Prof. at ICFO Adrian Bachtold, in partnership with researchers from Chalmers University of Technology and ETH Zurich, have established an explanation of the non-linear dissipation process with the help of a nano-mechanical resonator based on multilayer graphene. 
                In their research, the research team used a graphene-based nano-mechanical resonator, perfectly suited for viewing nonlinear effects in energy decay processes, and measured it with a superconducting microwave cavity. Such a system is can detect the mechanical vibrations in a very short span of time as well as being adequately sensitive to detect minimum displacements and over a very wide range of vibrational amplitudes. 
                The team took the system, forced it out-of-equilibrium with a driving force, and then turned off the force to measure the vibrational amplitude as the energy of the system decayed. They performed more than 1000 measurements for every energy decay trace and were able to see that as the energy of a vibrational mode decays, the rate of decay touches a point where it alters sharply to a lower value. The larger energy decay at high amplitude vibrations can be described using a model where the measured vibration mode “hybridizes” with another mode of the system and they decay in agreement. This is same as the coupling of the guitar string to the body although the coupling is nonlinear with regards to the graphene nano resonator. As the vibrational amplitude reduces, the rate abruptly changes and the modes become decoupled, causing comparatively low decay rates, thus in very huge quality factors beyond 1 million. This sudden alteration in the decay has never been measured or predicted thus far. 
                Therefore, the results attained in this research have illustrated that nonlinear effects in graphene nano-mechanical resonators expose a hybridization effect at high energies that, if controlled, could pave the way to new possibilities to control vibrational states, to analyze the collective motion of highly tunable systems, and engineer hybrid states with mechanical modes at totally different frequencies."""
        
        prompt = f"""
            You are a precise news entity extraction API.

            Your job is to extract named entities explicitly mentioned in the input text.

            Scope:
            - Focus primarily on organizations/startups.
            - Also extract other named entities when clearly present.

            Allowed entity types:
            - organization/startup
            - person
            - location
            - institution
            - investor

            Rules:
                1. Extract ONLY entities explicitly named in the text. Never infer, guess, or use external knowledge.
                2. Preserve exact casing as written in the source text.
                3. If both full name and abbreviation appear, keep ONLY the full name (e.g. keep "U.S. Securities and Exchange Commission", drop "SEC").
                4. Extract each entity only once. No duplicates.
                5. When unsure about any entity, skip it. Precision over recall.
                6. Do NOT extract product names, service names, or generic words.
                7. Use the most specific type when an entity fits multiple (e.g. "Harvard University" → institution, not location).
                8. Extract country names, city names, and regions as location type, even when used as geopolitical actors (e.g. "US", "Iran").
                9. If no entities are found, return an empty list.
                10. Output must be strict valid JSON only. No markdown, no explanation, no extra text.
                11. Never extract monetary values, percentages, or numbers as entities (e.g. "$50M", "10%", "2024").
                12. Never extract job titles or roles as entities (e.g. "CEO", "Chairman", "Founder") — only the person's actual name.
                13. Never extract time references as entities (e.g. "Q3", "Monday", "this year", "2024").
                14. If an entity is only implied by a pronoun (e.g. "he", "they", "it"), do not extract it.
                15. Never extract industry terms or sector names as entities (e.g. "fintech", "AI", "crypto", "SaaS").
                16. If a location is part of a company name, do not extract it separately (e.g. in "Bank of America", do not extract "America" as a location).
                17. Never extract adjectives derived from entity names as entities (e.g. "American", "Chinese", "Israeli").
                18. If a person is referenced only by their last name or first name alone, extract it only if it is completely unambiguous from context.
                19. Never extract hypothetical or speculative entities (e.g. "a potential acquirer", "an unnamed investor").
                20. Never extract entities from quoted speech that are not real-world entities (e.g. metaphors, analogies).
                21. do not add anything in the response that can not convert into the json direct your response

            Return exactly this schema:
            {{"entities": [{{"name": "string", "type": "string"}}]}}

            Input text:
            Title: {title}
            Description: {desc}
        """
        self.send_prompt(prompt)
        self.random_sleep(10,15)
        print(self.extract_response())

    def send_prompt(self,prompt):
        text_area = self.find_element('text area', '//div[@id="prompt-textarea"]')

        if text_area:
            self.driver.execute_script("""
                const el = arguments[0];
                const text = arguments[1];

                el.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);

                const event = new InputEvent('input', {
                    bubbles: true,
                    cancelable: true,
                    data: text
                });

                el.innerHTML = '<p>' + text + '</p>';
                el.dispatchEvent(event);
            """, text_area, prompt)
            time.sleep(1)
            self.click_element('send btn', '//button[@data-testid="send-button"]')

    def extract_response(self):
        all_chat = self.driver.find_elements(By.TAG_NAME,'section')
        if all_chat:
            last_response = all_chat[-1]
            last_response_text = last_response.text
            if 'ChatGPT said:\n' in last_response_text:
                last_response_text = last_response.text.replace('ChatGPT said:\n','')
            response_text = json.loads(last_response_text)
        return response_text

    def CloseDriver(self):
        try:self.driver.quit()
        except : ...