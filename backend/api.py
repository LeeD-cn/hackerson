"""HTTP transport for the shared v0.1 operations."""
import logging
import sqlite3

from fastapi import Body, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from contracts.planning import PlanningChat, PlanningEdit, PlanningVersion
from .planning import PlanningService
from .store import DomainError, OPERATIONS, Store

logger = logging.getLogger(__name__)


def error_response(status, code, message, details=None):
    error = {'code': code, 'message': message}
    if details is not None:
        error['details'] = details
    return JSONResponse(status_code=status, content={'error': error})


def create_app(db_path, admin_token, *, planning_model=None):
    app = FastAPI(title='Relay collaboration backend', version='0.1.0',
                  docs_url=None, redoc_url=None, openapi_url=None)
    store = Store(db_path, admin_token)
    app.state.store = store
    planning = PlanningService(store, planning_model)
    app.state.planning = planning

    def bearer(authorization):
        parts = authorization.split()
        return parts[1] if len(parts) == 2 and parts[0].lower() == 'bearer' else ''

    @app.middleware('http')
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return error_response(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Exclude raw inputs and exception context, which may contain credentials/private text.
        return error_response(422, 'invalid_input', '请求体应为合法的 JSON 参数对象', [
            {'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in exc.errors()
        ])

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(exc.status_code, 'not_found' if exc.status_code == 404 else 'http_error',
                              '路径不存在' if exc.status_code == 404 else '不支持此请求方式')

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        logger.error('Database operation failed: type=%s', type(exc).__name__)
        return error_response(500, 'internal_error', '数据库操作失败，请稍后重试或检查服务配置')

    @app.get('/api/planning/drafts')
    def list_drafts(authorization: str = Header(default='')):
        return planning.list(bearer(authorization))

    @app.get('/api/planning/drafts/{draft_id}')
    def get_draft(draft_id: str, authorization: str = Header(default='')):
        return planning.get(bearer(authorization), draft_id)

    @app.post('/api/planning/chat')
    def planning_chat(args: PlanningChat, authorization: str = Header(default='')):
        return planning.chat(bearer(authorization), args)

    @app.put('/api/planning/drafts/{draft_id}')
    def edit_draft(draft_id: str, args: PlanningEdit, authorization: str = Header(default='')):
        return planning.edit(bearer(authorization), draft_id, args)

    @app.post('/api/planning/drafts/{draft_id}/confirm')
    def confirm_draft(draft_id: str, args: PlanningVersion, authorization: str = Header(default='')):
        return planning.confirm(bearer(authorization), draft_id, args)

    @app.get('/health')
    def health():
        return {'status': 'ok', 'version': '0.1.0'}

    @app.get('/api/tool-schemas')
    def schemas():
        return {name: model.model_json_schema() for name, model in OPERATIONS.items()}

    @app.post('/api/tools/{action}')
    def call_tool(action: str, arguments: dict = Body(...), authorization: str = Header(default='')):
        token = bearer(authorization)
        try:
            return store.run(action, arguments, token)
        except DomainError:
            raise
        except sqlite3.OperationalError as exc:
            # Log the operation and error class only; no request data or SQL parameter values.
            logger.error('Database operation failed: action=%s type=%s', action, type(exc).__name__)
            return error_response(500, 'internal_error', '数据库操作失败，请稍后重试或检查服务配置')
        except Exception as exc:
            logger.error('Operation failed: action=%s type=%s', action, type(exc).__name__)
            return error_response(500, 'internal_error', '服务内部错误，请联系后端维护者')

    return app
