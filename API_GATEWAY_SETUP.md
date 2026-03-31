# API Gateway configuration for the Lambda image workflow

This document describes how to configure API Gateway routes to match
`lambda_function.py`'s routing logic for uploads, downloads, and CORS.

## Required routes (HTTP API or REST API)

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/upload` | Request a presigned S3 upload URL (Unity uploads directly to S3). |
| POST | `/upload-request` | Alternate upload path (same behavior as `/upload`). |
| GET | `/download/{code}` | Resolve a QR code/short code into a presigned download URL. |
| GET | `/download` | Resolve a download URL with `?code=...` query parameter. |
| OPTIONS | `/{proxy+}` or the specific routes above | CORS preflight handling. |

## Lambda integration

Attach all the routes above to the same Lambda function. The handler inspects
`httpMethod` and `path` to determine whether to handle an upload or download
request, and returns JSON with CORS headers.

## IAM permissions note (Access denied to apigateway:PUT)

If you see an error similar to **Access denied to apigateway:PUT**, your IAM
user/role does not have permission to create or modify API Gateway resources.
Ask your AWS administrator to grant API Gateway management permissions (for
example, attach `AmazonAPIGatewayAdministrator` or an equivalent policy that
allows `apigateway:GET`, `apigateway:POST`, `apigateway:PUT`, and
`apigateway:DELETE` on the API Gateway resources you manage).

## Example HTTP API route setup

1. Create an **HTTP API** in API Gateway.
2. Add **integrations** for the Lambda function.
3. Add routes:
   - `POST /upload` → Lambda
   - `POST /upload-request` → Lambda
   - `GET /download/{code}` → Lambda
   - `GET /download` → Lambda
   - `OPTIONS /{proxy+}` → Lambda (or enable CORS on the API)

## Required Lambda environment variables

- `BUCKET_NAME`: S3 bucket for uploaded images.
- `TABLE_NAME`: DynamoDB table storing `{ code -> s3Key }` mappings.

Optional:
- `BASE_DOWNLOAD_URL`: Required if `createQrCode` is true (used to build QR URLs).
- `QR_BUCKET_NAME`: S3 bucket for QR PNGs (defaults to `BUCKET_NAME`).
- `URL_EXPIRES_IN`: Presigned URL expiration in seconds (default `900`).

## Request/response summary

### Upload request

**POST** `/upload`

```json
{
  "filename": "photo.png",
  "contentType": "image/png",
  "createQrCode": true
}
```

Response fields include:
- `uploadUrl` (presigned S3 PUT URL)
- `code` (short code to later resolve)
- `downloadUrl` (when a base download URL is available)

### Download request

**GET** `/download/{code}` or `/download?code=...`

Returns a presigned S3 GET URL and the stored S3 key.
