import os
from celery import Celery

# Настройки Celery (Redis как брокер)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = Celery('genai_dashboard', broker=REDIS_URL)
app.conf.result_backend = REDIS_URL

@app.task(name="example_task")
def example_task():
    return "Worker is active!"