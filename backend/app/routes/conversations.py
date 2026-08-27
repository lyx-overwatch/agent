"""Conversation endpoints — create, list, delete, and file management."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.dependencies import get_current_user
from app.schemas.conversation import AddFilesResponse, CreateConversationResponse, FileTreeResponse
from app.services.chat import ChatService
from app.services.conversation_service import ConversationService
from app.utils import read_uploaded_files
from app.utils.rate_limit import check_conversation_create

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=CreateConversationResponse)
async def create_conversation(
    user_id: str = Depends(get_current_user),
    files: list[UploadFile] = File(default=[]),
):
    """创建新会话，可选上传文件。

    返回 conversation_id 和 thread_id，后续 /chat/stream 必须带上。
    thinking_enabled 改为按消息粒度在 /chat/stream 中控制。
    """
    await check_conversation_create(user_id)
    svc = ConversationService()
    file_data = await read_uploaded_files(files)
    result = await svc.create_conversation(user_id=user_id, file_data=file_data)
    return CreateConversationResponse(**result)


@router.post("/{conversation_id}/files", response_model=AddFilesResponse)
async def add_files_to_conversation(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
    files: list[UploadFile] = File(...),
):
    """向已有会话追加文件。"""
    svc = ConversationService()
    file_data = await read_uploaded_files(files)
    result = await svc.add_files_to_conversation(
        user_id=user_id,
        conversation_id=conversation_id,
        file_data=file_data,
    )
    return AddFilesResponse(**result)


@router.get("")
async def list_conversations(
    user_id: str = Depends(get_current_user),
):
    """获取当前用户的所有对话列表，按最近活动时间倒序。"""
    svc = ConversationService()
    return await svc.list_conversations(user_id)


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
):
    """删除指定对话及其所有消息、日志。"""
    try:
        svc = ConversationService()
        return await svc.delete_conversation(conversation_id, user_id)
    except HTTPException:
        raise


@router.get("/{conversation_id}/files/tree", response_model=FileTreeResponse)
async def file_tree(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
):
    """获取对话的文件树（outputs / workspace / uploads）。

    返回三个根节点的递归文件树，前端可通过树形组件展示，
    点击文件时使用 GET /chat/files/{conversation_id}?path={virtual_path} 预览。"""
    svc = ChatService()
    return await svc.build_file_tree(conversation_id, user_id)
