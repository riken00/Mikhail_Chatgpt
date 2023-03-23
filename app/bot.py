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
        self.email = os.getenv('EMAIL').replace('@gmail.com','')+'+'+str(random.randint(10000,99999))+'@gmail.com'
        self.password = os.getenv('EMAIL_PASSWORD')
        
    def get_driver(self,profile_name='Default',profileDict = 'Profiles') :
        options = webdriver.ChromeOptions()
        profile_name = str(profile_name)
        self.profile = profile_name
        options.add_argument(f"--user-data-dir={profileDict}") 
        options.add_argument(f'--profile-directory={profile_name}')
        # options.headless = True
        self.driver = uc.Chrome(use_subprocess=True,options=options)
        self.driver.maximize_window()
        # self.driver = webdriver.Chrome(ChromeDriverManager().install())
        
        # profile = webdriver.FirefoxProfile('Profiles_FF')
        # self.driver = webdriver.Firefox(profile)
        # self.driver.maximize_window()
        
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

    def singup(self,profile_name=''):
        print('11')
        self.get_driver(profile_name )
        
        self.driver.get('https://myaccount.google.com/')
        
        check_account = self.find_element('check account','/html/body/header/div[1]/div[5]/ul/li[2]/a',timeout=5)
        if check_account : 
            if check_account.text == 'Go to Google Account': 
                check_account.click()
                account_added = self.login_gmail()
        self.driver.get('https://chat.openai.com/chat')
        LogOutbtn = self.click_element('log out','/html/body/div[1]/div[1]/div[2]/div/div/nav/a[5]')
        if LogOutbtn:self.random_sleep()
        for _ in range(50):
                self.driver.refresh()
                welcome_ele = self.find_element('Welcome','//*[@id="__next"]/div[1]/div/div[3]',timeout=2)
                if welcome_ele:
                    if welcome_ele.text == 'Log in with your OpenAI account to continue': break
            
        else:
            self.CloseDriver()
            return
        # time.sleep(random.randint(5,10))
        
        self.click_element('Sign up btn','//*[@id="__next"]/div[1]/div/div[4]/button[2]')
        self.random_sleep()
        create_acc_h1 = self.find_element('Create acc H1','/html/body/main/section/div/div/header/h1')
        if create_acc_h1:
            if 'Create your account' in create_acc_h1.text:
                # self.get_new_email()
                # self.change_window(0)
                break_outer = False
                for _ in range(3):
                    
                    toomany = self.find_element('too many signups','/html/body/main/section/div/div/div/div[1]/p',timeout=3)
                    if toomany:
                        if toomany.text == 'Too many signups from the same IP':
                            return False
                    
                    self.input_text(self.email,'Email input','//*[@id="email"]')
                    self.click_element('Continue','/html/body/main/section/div/div/div/form/div[3]/button')
                    self.random_sleep()
                    self.input_text(self.get_new_password(),'Password Input','//*[@id="password"]')
                    self.click_element('Continue','/html/body/main/section/div/div/div/form/div[3]/button')
                
                    for _ in range(3):
                        verify_enail = self.find_element('Verify email','//*[@id="root"]/div[1]/div/div[2]/h1')
                        if verify_enail:
                            if verify_enail.text == "Verify your email":
                                break_outer = True
                                break
                    if break_outer:break

                self.verify_email()
                
        fake = Faker()
        name = fake.name()
        name_li = str(name).split(' ')
        self.change_window(-1)
        self.input_text('Fiestname',name_li[0],'//*[@id="root"]/div[1]/div/div[2]/form/div/div/div[1]/input')
        self.input_text('lastnamw',name_li[1],'//*[@id="root"]/div[1]/div/div[2]/form/div/div/div[2]/input')
        time.sleep(2)
        self.click_element('Continue','//*[@id="root"]/div[1]/div/div[2]/form/button')
        
        
        sent_otp = False
        get_otp = False
        # get mobile number
        for _ in range(3):
            for i in range(5):
                
                number = get_number()
                if not number : continue
                self.get_ready_number_page()
                splited_number = number[2:]
                self.input_text(splited_number,'Phone number','//*[@id="root"]/div[1]/div/div[2]/form/div[1]/div/div[2]/input')
                self.click_element('send sms','/html/body/div[1]/div[1]/div/div[2]/form/button')
                
                self.random_sleep()
                code_sent_confirmation = self.find_element('enter code','/html/body/div[1]/div[1]/div/div[2]/h1',timeout=30)
                if code_sent_confirmation:
                    if code_sent_confirmation.text == 'Enter code': 
                        sent_otp = True
                        break
                    else : self.click_element('Go back','/html/body/div[1]/div[1]/div/div[3]')
                else : self.click_element('Go back','/html/body/div[1]/div[1]/div/div[3]',timeout=0)
                
            if not sent_otp : 
                ban_number(number)
                self.click_element('Go back','/html/body/div[1]/div[1]/div/div[3]')
                continue
                
            for _ in range(3):
                print(f'trying to get otp : {_+1} Time')
                otp = get_sms(number)
                if otp : 
                    get_otp = True
                    break
            else: 
                ban_number(number)
                self.click_element('Go back','/html/body/div[1]/div[1]/div/div[3]')

            if get_otp : break
        
        
        self.input_text(otp,'otp input','/html/body/div[1]/div[1]/div/div[2]/form/div/div/input')
        
        self.random_sleep(10,15)
        self.driver.refresh()
        self.click_element('Next btn','/html/body/div[3]/div/div/div/div[2]/div/div/div[2]/div[4]/button')
        self.click_element('Next btn','/html/body/div[3]/div/div/div/div[2]/div/div/div[2]/div[4]/button[2]')
        self.click_element('Next btn','/html/body/div[3]/div/div/div/div[2]/div/div/div[2]/div[4]/button[2]')
        
        userr = user_details.objects.create(
            email = self.email,
            password = self.password,
            profile = self.profile
        )
        
        userr.ProfileDict = str(int(userr.id%10))
        userr.save()
        
        self.click_element('log out','/html/body/div[1]/div[1]/div[2]/div/div/nav/a[5]')

        self.random_sleep(20,50)
                            
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

    def work(self,UserEmail,UserPassword):
        
        self.driver.get('https://chat.openai.com/chat')
        while True:
            time.sleep(3)
            capacity = self.find_element('High capacity','//*[@id="__next"]/div[1]/div/div/div[1]/div[1]',timeout=2)
            if capacity:
                if 'capacity' in capacity.text.lower():
                    self.driver.refresh()
                    continue
            break                

        login_btn = self.find_element('Login btn','//*[@id="__next"]/div[1]/div/div[4]/button[1]',timeout=2)
        if login_btn:
            if login_btn.text == 'Log in':
                self.sign_in(UserEmail,UserPassword)
                self.click_element('Next pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button',timeout=2)
                self.click_element('Next2 pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button[2]',timeout=2)
                self.click_element('Done pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button[2]',timeout=2)
        
        session_expired = self.find_element('Login expires','//*[@id="headlessui-dialog-title-:r2:"]')
        if session_expired :
            if session_expired.text == 'Your session has expired':
                self.click_element('Login','/html/body/div[3]/div/div/div/div[2]/div/div/div[2]/button')
                self.sign_in(UserEmail,UserPassword)
                self.click_element('Next pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button',timeout=2)
                self.click_element('Next2 pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button[2]',timeout=2)
                self.click_element('Done pop up btn','//*[@id="headlessui-dialog-panel-:r1:"]/div[2]/div[4]/button[2]',timeout=2)
                
        
        time.sleep(random.randint(5,10))

        verify_one = self.find_element('Captcha','//*[@id="cf-stage"]/div[6]/label',timeout=2)
        if verify_one:
            if str(verify_one.text).upper() == "Verify you are human".upper():
                self.click_element('Verify box','//*[@id="cf-stage"]/div[6]/label/span',timeout=3)

        verify_two = self.click_element('Verify2','//*[@id="challenge-stage"]/div/input',timeout=2)
        if verify_two:
            if str(verify_two.text).upper() == "Verify you are human".upper():
                verify_two.click()
            
        
        sounds_good = self.find_element('Sounds good','//*[@id="headlessui-dialog-panel-:r1:"]/div[3]/button',timeout=3)
        if sounds_good:
            if sounds_good.text.upper() == "Sounds good!".upper():
                sounds_good.click()
                
        count_sentence = 0
        for _ in range(random.randint(10,20)):
            self.all_response_text = []
            count_sentence+=1
            text = TxtObj.objects.filter(pharaphreased="NOT_DONE").first() 
            text.pharaphreased = "RUNNING"
            text.save()
            time.sleep(random.randint(5,10))
            Text = text.text
            print(Text)
            
            response = 0
            self.pharaprase_text(Text=Text,response=response)
            for i in range(6):
                response = self.pharaprase_text(number=random.randint(10,15),Text=Text,another=True,response=response)
                if response > 50: break
            
            print('response',response)
            self.AddPraprasedSentenceIntoList()
                

            if self.not_found_bool == False:
                number_count = 1
                

                PageTitle = self.driver.title
                for response in self.all_response_text :
                    print(number_count,response)
                    ParaphrasedText.objects.create(
                        sentence = text,
                        response = response,
                        PageTitle = PageTitle,
                        number = number_count 
                    )
                    number_count += 1
                    
                text.pharaphreased = "DONE"
                text.save()
            
            self.click_element('Clear conversation','//*[@id="__next"]/div[1]/div[2]/div/div/nav/a[2]')
            time.sleep(2)
            self.click_element('Confirm clear conversation','//*[@id="__next"]/div[1]/div[2]/div/div/nav/a[2]')
            self.driver.refresh()
            # self.CloseDriver()
            # self.get_driver()
            # self.driver.get('https://chat.openai.com/chat')
        self.CloseDriver()

    def CloseDriver(self):
        try:self.driver.quit()
        except : ...