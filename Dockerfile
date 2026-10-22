FROM python:3.14
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate && exec gunicorn library_management.wsgi -b 0.0.0.0:8000"]
