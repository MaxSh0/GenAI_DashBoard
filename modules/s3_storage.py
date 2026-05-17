import os
import boto3
from botocore.exceptions import ClientError
from modules.settings import S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY


class S3Manager:
    """Thin wrapper around the boto3 S3 client configured for MinIO (or any S3-compatible storage).

    Provides convenience methods for bucket management, file upload/download, and direct
    text content read/write.
    """

    def __init__(self):
        """Initialize the boto3 S3 client using settings from the application config."""
        self.s3 = boto3.client(
            's3',
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name='us-east-1',
        )

    def init_buckets(self, buckets):
        """Ensure the given buckets exist, creating any that are missing.

        Args:
            buckets (list of str): Bucket names to check/create.
        """
        for bucket in buckets:
            try:
                self.s3.head_bucket(Bucket=bucket)
            except ClientError:
                self.s3.create_bucket(Bucket=bucket)

    def list_files(self, bucket, prefix=""):
        """List all object keys in a bucket, optionally filtered by a prefix.

        Directory-like keys (those ending with ``/``) are excluded from the result.

        Args:
            bucket (str): S3 bucket name.
            prefix (str): Optional key prefix filter.

        Returns:
            list of str: Object keys in the bucket.
        """
        try:
            response = self.s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
            if 'Contents' in response:
                return [obj['Key'] for obj in response['Contents'] if not obj['Key'].endswith('/')]
            return []
        except Exception as e:
            print(f"S3 List Error: {e}")
            return []

    def upload_file(self, local_path, bucket, object_name=None):
        """Upload a local file to S3.

        Args:
            local_path (str): Path to the local file.
            bucket (str): Destination bucket name.
            object_name (str): S3 object key. Defaults to the file's basename.
        """
        if object_name is None:
            object_name = os.path.basename(local_path)
        self.s3.upload_file(local_path, bucket, object_name)

    def download_file(self, bucket, object_name, local_path):
        """Download an object from S3 to a local path, creating parent directories as needed.

        The file is always re-downloaded to guarantee freshness. For production use,
        an ETag-based check could be added to skip unchanged files.

        Args:
            bucket (str): S3 bucket name.
            object_name (str): S3 object key to download.
            local_path (str): Local filesystem destination path.
        """
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        self.s3.download_file(bucket, object_name, local_path)

    def put_text(self, bucket, object_name, text_content):
        """Write a string directly to an S3 object without an intermediate local file.

        Args:
            bucket (str): S3 bucket name.
            object_name (str): S3 object key.
            text_content (str): Text content to store.
        """
        self.s3.put_object(Bucket=bucket, Key=object_name, Body=text_content.encode('utf-8'))

    def get_text(self, bucket, object_name):
        """Read the contents of an S3 object as a UTF-8 string.

        Args:
            bucket (str): S3 bucket name.
            object_name (str): S3 object key.

        Returns:
            str: Decoded text content of the object.
        """
        response = self.s3.get_object(Bucket=bucket, Key=object_name)
        return response['Body'].read().decode('utf-8')

    def delete_file(self, bucket, object_name):
        """Delete an object from S3.

        Args:
            bucket (str): S3 bucket name.
            object_name (str): S3 object key to delete.
        """
        self.s3.delete_object(Bucket=bucket, Key=object_name)


s3_client = S3Manager()
