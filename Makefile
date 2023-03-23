env:
	sudo apt install python3-pip
	pip3 install virtualenv
	python3 -m venv env

install: requirements.txt 
	pip3 install -r requirements.txt 

migrate:
	python manage.py makemigrations
	python manage.py migrate

scrape:
ifdef n
	python manage.py scrape --n=$(n)
else
	python manage.py scrape
endif

add_data:
	python manage.py add_text

signup:
# make signup n=$$n
ifdef n
	python manage.py signup --n=$(n)
else
	python manage.py signup
endif

