"""Storage diagnostic endpoints — direct OBS/S3 connection, upload, list, delete.

These bypass the agent loop entirely so object-storage connectivity can be
verified quickly after deployment without spinning up a sandbox container.
"""

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_user
from app.schemas.storage import StorageUploadRequest
from app.services.storage_service import StorageService

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/health")
async def storage_health(user_id: str = Depends(get_current_user)):
    """测试 OBS/S3 连接、认证与 bucket 是否存在。"""
    return await StorageService.health()


@router.post("/upload")
async def storage_upload(req: StorageUploadRequest, user_id: str = Depends(get_current_user)):
    """上传一个测试文件，返回 storage key 与下载 URL。"""
    return await StorageService.upload(content=req.content, name=req.name, prefix=req.prefix)


@router.get("/url")
async def storage_download_url(
    key: str = Query(..., description="对象 key，生成下载 URL（不实际上传）"),
    download: bool = Query(False, description="是否生成 attachment 下载 URL"),
    expires_in: int = Query(3600, description="URL 有效期（秒）"),
    user_id: str = Depends(get_current_user),
):
    """生成一个对象的下载 URL，不执行上传（用于验证 OBS 代理下载链路）。"""
    return await StorageService.download_url(key=key, expires_in=expires_in, download=download)


@router.get("/list")
async def storage_list(
    prefix: str = Query("", description="对象前缀，留空列出根目录"),
    user_id: str = Depends(get_current_user),
):
    """列出指定前缀下的对象。"""
    return await StorageService.list_objects(prefix=prefix)


@router.delete("/object")
async def storage_delete(
    key: str = Query(..., description="要删除的对象 key"),
    user_id: str = Depends(get_current_user),
):
    """删除指定 key 的对象。"""
    return await StorageService.delete(key=key)
