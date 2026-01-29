import base64
import io
import json
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs

import boto3
import qrcode


S3_CLIENT = boto3.client("s3")
DDB_CLIENT = boto3.client("dynamodb")


def _json_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def _get_body(event):
    if not event.get("body"):
        return {}
    if event.get("isBase64Encoded"):
        decoded = base64.b64decode(event["body"]).decode("utf-8")
        return json.loads(decoded)
    return json.loads(event["body"])


def _get_path(event):
    return event.get("rawPath") or event.get("path") or ""


def _get_query_params(event):
    if event.get("queryStringParameters"):
        return event["queryStringParameters"]
    if event.get("rawQueryString"):
        return {k: v[0] for k, v in parse_qs(event["rawQueryString"]).items()}
    return {}


def _get_download_base_url(event):
    env_base = os.getenv("BASE_DOWNLOAD_URL")
    if env_base:
        return env_base.rstrip("/")
    headers = event.get("headers") or {}
    host = headers.get("Host") or headers.get("host")
    stage = event.get("requestContext", {}).get("stage")
    if host:
        if stage:
            return f"https://{host}/{stage}/download"
        return f"https://{host}/download"
    return ""


def _put_qr_code(bucket, key, url):
    image = qrcode.make(url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    S3_CLIENT.put_object(
        Bucket=bucket,
        Key=key,
        Body=buffer.getvalue(),
        ContentType="image/png",
    )


def _store_mapping(table_name, code, s3_key, content_type, qr_key=None):
    item = {
        "code": {"S": code},
        "s3Key": {"S": s3_key},
        "contentType": {"S": content_type},
        "createdAt": {"S": datetime.now(timezone.utc).isoformat()},
    }
    if qr_key:
        item["qrKey"] = {"S": qr_key}
    DDB_CLIENT.put_item(TableName=table_name, Item=item)


def _get_mapping(table_name, code):
    response = DDB_CLIENT.get_item(
        TableName=table_name,
        Key={"code": {"S": code}},
    )
    return response.get("Item")


def _handle_upload_request(event):
    body = _get_body(event)
    filename = body.get("filename")
    content_type = body.get("contentType", "application/octet-stream")
    if not filename:
        return _json_response(400, {"message": "filename is required"})

    bucket = os.getenv("BUCKET_NAME")
    table_name = os.getenv("TABLE_NAME")
    if not bucket or not table_name:
        return _json_response(500, {"message": "Missing BUCKET_NAME or TABLE_NAME"})

    code = body.get("code") or uuid.uuid4().hex
    s3_key = f"uploads/{code}/{filename}"

    presigned = S3_CLIENT.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": s3_key, "ContentType": content_type},
        ExpiresIn=int(os.getenv("URL_EXPIRES_IN", "900")),
    )

    qr_bucket = os.getenv("QR_BUCKET_NAME", bucket)
    qr_key = None
    download_base = _get_download_base_url(event)
    download_url = f"{download_base}/{code}" if download_base else ""

    if body.get("createQrCode"):
        if not download_url:
            return _json_response(
                400,
                {
                    "message": "BASE_DOWNLOAD_URL is required when createQrCode is true",
                },
            )
        qr_key = f"qr/{code}.png"
        _put_qr_code(qr_bucket, qr_key, download_url)

    _store_mapping(table_name, code, s3_key, content_type, qr_key)

    return _json_response(
        200,
        {
            "code": code,
            "uploadUrl": presigned,
            "s3Key": s3_key,
            "qrCodeKey": qr_key,
            "downloadUrl": download_url,
        },
    )


def _handle_download_request(event, code):
    bucket = os.getenv("BUCKET_NAME")
    table_name = os.getenv("TABLE_NAME")
    if not bucket or not table_name:
        return _json_response(500, {"message": "Missing BUCKET_NAME or TABLE_NAME"})

    item = _get_mapping(table_name, code)
    if not item:
        return _json_response(404, {"message": "Code not found"})

    s3_key = item["s3Key"]["S"]
    content_type = item.get("contentType", {}).get("S")

    presigned = S3_CLIENT.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=int(os.getenv("URL_EXPIRES_IN", "900")),
    )

    response = {
        "code": code,
        "downloadUrl": presigned,
        "s3Key": s3_key,
        "contentType": content_type,
    }

    if "qrKey" in item:
        response["qrCodeKey"] = item["qrKey"]["S"]

    return _json_response(200, response)


def lambda_handler(event, context):
    method = event.get("httpMethod")
    path = _get_path(event)

    if method == "OPTIONS":
        return _json_response(200, {"message": "ok"})

    if method == "POST" and path.rstrip("/") in {"/upload", "/upload-request"}:
        return _handle_upload_request(event)

    if method == "GET":
        query_params = _get_query_params(event)
        code = query_params.get("code")

        if not code:
            segments = [segment for segment in path.split("/") if segment]
            if len(segments) >= 2 and segments[-2] == "download":
                code = segments[-1]

        if code:
            return _handle_download_request(event, code)

    return _json_response(404, {"message": "Not Found"})
