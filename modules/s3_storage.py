import os
import boto3
from botocore.exceptions import ClientError
from modules.settings import S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY

class S3Manager:
    def __init__(self):
        self.s3 = boto3.client(
            's3',
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name='us-east-1' # Для MinIO регион можно оставить дефолтным
        )

    def init_buckets(self, buckets):
        """Создает бакеты при старте приложения, если их нет."""
        for bucket in buckets:
            try:
                self.s3.head_bucket(Bucket=bucket)
            except ClientError:
                self.s3.create_bucket(Bucket=bucket)

    def list_files(self, bucket, prefix=""):
        """Возвращает список имен файлов в бакете."""
        try:
            response = self.s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
            if 'Contents' in response:
                return [obj['Key'] for obj in response['Contents'] if not obj['Key'].endswith('/')]
            return []
        except Exception as e:
            print(f"S3 List Error: {e}")
            return []

    def upload_file(self, local_path, bucket, object_name=None):
        """Загружает локальный файл в S3."""
        if object_name is None:
            object_name = os.path.basename(local_path)
        self.s3.upload_file(local_path, bucket, object_name)

    def download_file(self, bucket, object_name, local_path):
        """Скачивает файл из S3 в локальный кэш (если он изменился или его нет)."""
        # В идеале здесь можно добавить проверку ETag (хэша), чтобы не качать каждый раз, 
        # но для начала качаем всегда, чтобы гарантировать свежесть кода.
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        self.s3.download_file(bucket, object_name, local_path)

    def put_text(self, bucket, object_name, text_content):
        """Сохраняет строку (например, код) прямо в S3 без промежуточного файла."""
        self.s3.put_object(Bucket=bucket, Key=object_name, Body=text_content.encode('utf-8'))

    def get_text(self, bucket, object_name):
        """Читает текст (код) напрямую из S3."""
        response = self.s3.get_object(Bucket=bucket, Key=object_name)
        return response['Body'].read().decode('utf-8')

    def delete_file(self, bucket, object_name):
        """Удаляет файл из S3."""
        self.s3.delete_object(Bucket=bucket, Key=object_name)

# Создаем глобальный экземпляр (Singleton)
s3_client = S3Manager()