"""에러 코드 관리 + 전역 예외 처리.

구조 (Spring 의 ErrorCode enum / CustomRuntimeException / ControllerAdvice 대응):
- ErrorCode: 에러 코드 정의 enum (HTTP 상태, 코드, 기본 메시지, 로그 레벨)
- AppException: ErrorCode 기반 도메인 예외. 발생 시점에 해당 로그 레벨로 즉시 로깅
- register_exception_handlers: 모든 예외를 CommonResponse(success=False)로 변환
"""

import logging
from enum import Enum
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas import CommonResponse

logger = logging.getLogger("app")


class ErrorCode(Enum):
    """(HTTP 상태, 에러 코드, 기본 메시지, 로그 레벨)"""

    # COMMON
    VALIDATION_ERROR = (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "COMMON_001",
        "요청 형식이 올바르지 않습니다.",
        logging.WARNING,
    )
    HTTP_ERROR = (
        HTTPStatus.BAD_REQUEST,
        "COMMON_002",
        "요청을 처리할 수 없습니다.",
        logging.WARNING,
    )
    INTERNAL_SERVER_ERROR = (
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "COMMON_003",
        "서버 내부 오류가 발생했습니다.",
        logging.ERROR,
    )

    # LLM
    LLM_SERVICE_ERROR = (
        HTTPStatus.BAD_GATEWAY,
        "LLM_001",
        "LLM 호출 중 오류가 발생했습니다.",
        logging.ERROR,
    )

    def __init__(self, status: HTTPStatus, code: str, message: str, log_level: int):
        self.status = status
        self.code = code
        self.message = message
        self.log_level = log_level


class AppException(Exception):
    """ErrorCode 를 담는 도메인 예외.

    사용: raise AppException(ErrorCode.LLM_SERVICE_ERROR, "상세 설명")
    발생 시점에 ErrorCode 에 정의된 로그 레벨로 즉시 로깅한다.
    """

    def __init__(self, error_code: ErrorCode, details: str | None = None):
        self.error_code = error_code
        self.details = details
        self.message = (
            error_code.message
            if details is None
            else f"{error_code.message}: {details}"
        )
        super().__init__(self.message)
        logger.log(error_code.log_level, "[%s] %s", error_code.code, self.message)


def _error_response(
    status_code: int, code: str, message: str, data: Any = None
) -> JSONResponse:
    body = CommonResponse[Any](success=False, code=code, message=message, data=data)
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        # 로깅은 예외 생성 시점에 이미 수행됨
        return _error_response(exc.error_code.status, exc.error_code.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        ec = ErrorCode.VALIDATION_ERROR
        logger.log(ec.log_level, "[%s] %s %s", ec.code, request.url.path, exc.errors())
        return _error_response(ec.status, ec.code, ec.message, exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        ec = ErrorCode.HTTP_ERROR
        # 상태 코드는 예외가 가진 값(404 등)을 그대로 사용
        return _error_response(exc.status_code, ec.code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        ec = ErrorCode.INTERNAL_SERVER_ERROR
        logger.exception("[%s] %s %s", ec.code, request.method, request.url.path)
        return _error_response(ec.status, ec.code, ec.message)
