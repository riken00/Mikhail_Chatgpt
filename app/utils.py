from tqdm import tqdm
import json, os, re
from .models import Text
import random

class SeprateText:
    
    files = os.listdir('TextJsons')
    def __init__(self):
        self.variable()
        
        for filename in self.files:
            new_data = []

            with open(f'TextJsons/{filename}', 'r', encoding='utf-8') as f:
                data = f.readlines()

            for line in data:
                new_data.append(json.loads(line)['text'].replace('\n', ' '))
                
            self.add_data(new_data)

    def variable(self):
        self.alphabets = "([A-Za-z])"
        self.prefixes = "(Mr|St|Mrs|Ms|Dr)[.]"
        self.suffixes = "(Inc|Ltd|Jr|Sr|Co)"
        self.starters = "(Mr|Mrs|Ms|Dr|He\s|She\s|It\s|They\s|Their\s|Our\s|We\s|But\s|However\s|That\s|This\s|Wherever)"
        self.acronyms = "([A-Z][.][A-Z][.](?:[A-Z][.])?)"
        self.websites = "[.](com|net|org|io|gov)"
        self.digits = "([0-9])"

    def split_into_sentences(self,text):
        text = " " + text + "  "
        text = text.replace("\n", " ")
        text = re.sub(self.prefixes, "\\1<prd>", text)
        text = re.sub(self.websites, "<prd>\\1", text)
        text = re.sub(self.digits + "[.]" + self.digits, "\\1<prd>\\2", text)
        if "..." in text:
            text = text.replace("...", "<prd><prd><prd>")
        if "Ph.D" in text:
            text = text.replace("Ph.D.", "Ph<prd>D<prd>")
        text = re.sub("\s" + self.alphabets + "[.] ", " \\1<prd> ", text)
        text = re.sub(self.acronyms+" "+self.starters, "\\1<stop> \\2", text)
        text = re.sub(self.alphabets + "[.]" + self.alphabets + "[.]" +
                    self.alphabets + "[.]", "\\1<prd>\\2<prd>\\3<prd>", text)
        text = re.sub(self.alphabets + "[.]" + self.alphabets +
                    "[.]", "\\1<prd>\\2<prd>", text)
        text = re.sub(" "+self.suffixes+"[.] "+self.starters, " \\1<stop> \\2", text)
        text = re.sub(" "+self.suffixes+"[.]", " \\1<prd>", text)
        text = re.sub(" " + self.alphabets + "[.]", " \\1<prd>", text)
        if "”" in text:
            text = text.replace(".”", "”.")
        if "\"" in text:
            text = text.replace(".\"", "\".")
        if "!" in text:
            text = text.replace("!\"", "\"!")
        if "?" in text:
            text = text.replace("?\"", "\"?")
        text = text.replace(".", ".<stop>")
        text = text.replace("?", "?<stop>")
        text = text.replace("!", "!<stop>")
        text = text.replace("<prd>", ".")
        sentences = text.split("<stop>")
        sentences = sentences[:-1]
        sentences = [s.strip() for s in sentences]
        return sentences
    
    
    def add_data(self,new_data):
        for sentences in tqdm(new_data):
            for sentence in self.split_into_sentences(sentences):
                if len(sentence) > 500:
                    continue
                matches = re.findall(
                    r'(http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])', sentence)
                if len(matches) > 0:
                    continue
                if len(sentence) < 10:
                    continue
                TextObj=Text.objects.create(
                            text = sentence
                        )
                print(TextObj.id,':',TextObj.text)