"""File upload endpoints for S3 presigned URLs and attachments."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends

from app.dependencies import get_client_ip, get_current_user
from app.schemas.upload import PresignedUrlRequest, UploadConfirm
from app.services.upload_service import UploadService

router = APIRouter()


@router.post("/presigned-url")
async def get_presigned_upload_url(
    payload: PresignedUrlRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Generate a presigned S3 upload URL for a ticket attachment."""
    service = UploadService()
    result = await service.generate_presigned_url(
        ticket_id=payload.ticket_id,
        file_name=payload.file_name,
        content_type=payload.content_type,
        file_size=payload.file_size,
    )
    return {"data": result}


@router.post("/confirm", status_code=201)
async def confirm_upload(
    payload: UploadConfirm,
    user: dict = Depends(get_current_user),
    ip_address: Optional[str] = Depends(get_client_ip),
) -> dict:
    """Confirm upload completion and create the attachment record."""
    service = UploadService()
    attachment = await service.confirm_upload(
        ticket_id=payload.ticket_id,
        s3_key=payload.s3_key,
        file_name=payload.file_name,
        content_type=payload.content_type,
        file_size=payload.file_size,
        user_id=user["id"],
        ip_address=ip_address,
    )
    return {"data": attachment, "message": "Upload confirmed"}


@router.get("/{ticket_id}")
async def list_attachments(
    ticket_id: UUID,
    user: dict = Depends(get_current_user),
) -> dict:
    """List all attachments for a ticket with presigned download URLs."""
    service = UploadService()
    attachments = await service.list_attachments(ticket_id, viewer=user)
    return {"data": attachments}


@router.delete("/{attachment_id}", status_code=204)
async def delete_attachment(
    attachment_id: UUID,
    user: dict = Depends(get_current_user),
    ip_address: Optional[str] = Depends(get_client_ip),
) -> None:
    """Delete an attachment (uploader or admin only)."""
    service = UploadService()
    await service.delete_attachment(attachment_id, user=user, ip_address=ip_address)
    return None
