from email.policy import HTTP
from http.client import HTTPResponse
from django.shortcuts import render
from selenium import webdriver
import undetected_chromedriver as uc
from django.views.generic import TemplateView, CreateView
from django.http import JsonResponse
import json, os
from selenium.common.exceptions import NoSuchElementException, TimeoutException,InvalidElementStateException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv
load_dotenv()
# Create your views here.


class VerifyEmail(TemplateView):
    
    def get_driver(self,profile_name='Default') :
        options = webdriver.ChromeOptions()
        
        options.add_argument(f"--user-data-dir=Profiles") 
        options.add_argument(f'--profile-directory={profile_name}')
        self.driver = uc.Chrome(use_subprocess=True,options=options)
    
    def login(self):
        
        ...

    def get(self,requests):
        self.get_driver('Gmail')
        self.driver.get('https://accounts.google.com/')
        signinH1 = self.find_element('Sign in Page','/html/body/div[1]/div[1]/div[2]/div/c-wiz/div/div[1]/div/h1/span')
        if signinH1:
            breakpoint()
            if signinH1.text == 'Sign in':
                self.input_text(os.getenv('EMAIL'),'Email input','//*[@id="identifierId"]'  )
                self.click_element('Next btn','//*[@id="identifierNext"]/div/button')
                
            
        breakpoint()
        return JsonResponse({'msg':'Sucessfull done'})
    
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
                #  ele = wait_obj.until(
                #          EC.presence_of_element_located(
                #              (locator_type, locator)))
                ele = wait_obj.until(
                        condition_func((locator_type, locator),
                            *condition_other_args))
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
            ele.clear()
            ele.send_keys(text)
            print(f'Inputed "{text}" for the element: {element}')
            return ele    
    
    
        
class check  :
    def get(self,requests):
        
        return HTTPResponse('Hello world')